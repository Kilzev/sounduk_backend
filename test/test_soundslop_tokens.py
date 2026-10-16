"""Тесты SoundSlop: токены (balance/ad-reward/redeem) и генерация (job-паттерн).

Провайдер fal.ai в тестах не сконфигурирован (SOUNDSLOP_PROVIDER_KEYS пуст) —
job должен завершаться failed с автоматическим refund токенов.
"""
import uuid

import pytest

import models
import soundslop_worker
import token_service
from conftest import TestingSessionLocal, register_and_login


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _grant_tokens(user_id: int, amount: int, reason: str = "admin_grant") -> None:
    """Прямое начисление токенов в ledger (эмуляция покупки/подписки)."""
    db = TestingSessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        token_service.apply_transaction(
            db,
            user=user,
            delta=amount,
            reason=reason,
            ref_id=f"test:{uuid.uuid4()}",
        )
    finally:
        db.close()


def _user_id(client, token: str) -> int:
    resp = client.get("/api/auth/me", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture(scope="module")
def slop_user(client):
    token = register_and_login(client, "slop_user")
    return token, _user_id(client, token)


class TestTokenBalance:
    def test_balance_defaults(self, client, slop_user):
        token, _ = slop_user
        resp = client.get("/api/tokens/balance", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == 0
        assert data["cost_per_generation"] == 10
        assert data["max_duration_sec"] == 180

    def test_balance_unauthorized(self, client):
        assert client.get("/api/tokens/balance").status_code in (401, 403)


class TestAdReward:
    def test_reward_grants_and_idempotent(self, client, slop_user):
        token, _ = slop_user
        key = f"ad:{uuid.uuid4()}"
        resp = client.post(
            "/api/tokens/ad-reward",
            json={"idempotency_key": key},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()
        assert first["granted"] == 1

        # Повтор с тем же ключом — без повторного начисления
        replay = client.post(
            "/api/tokens/ad-reward",
            json={"idempotency_key": key},
            headers=_auth(token),
        )
        assert replay.status_code == 200
        assert replay.json()["granted"] == 0
        assert replay.json()["balance"] == first["balance"]

    def test_daily_limit(self, client, slop_user, monkeypatch):
        token, _ = slop_user
        monkeypatch.setenv("SOUNDSLOP_AD_DAILY_LIMIT", "3")
        # У пользователя уже 1 награда из предыдущего теста — добиваем до лимита
        last_status = 200
        for _ in range(5):
            resp = client.post(
                "/api/tokens/ad-reward",
                json={"idempotency_key": f"ad:{uuid.uuid4()}"},
                headers=_auth(token),
            )
            last_status = resp.status_code
        assert last_status == 429


class TestRedeemStorage:
    def test_insufficient(self, client, slop_user):
        token, _ = slop_user
        balance = client.get("/api/tokens/balance", headers=_auth(token)).json()[
            "balance"
        ]
        if balance < token_service.tokens_per_gb():
            resp = client.post(
                "/api/tokens/redeem-storage",
                json={"gb": 1},
                headers=_auth(token),
            )
            assert resp.status_code == 402

    def test_redeem_success(self, client, slop_user):
        token, user_id = slop_user
        _grant_tokens(user_id, 100)
        before = client.get("/api/auth/me", headers=_auth(token)).json()
        resp = client.post(
            "/api/tokens/redeem-storage",
            json={"gb": 1},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["spent"] == token_service.tokens_per_gb()
        assert data["storage_limit"] == before["storage_limit"] + 1024**3


class TestGenerate:
    @pytest.fixture(autouse=True)
    def _worker_db(self, monkeypatch):
        """Воркер должен работать с тестовой in-memory БД."""
        monkeypatch.setattr(soundslop_worker, "SessionLocal", TestingSessionLocal)
        monkeypatch.delenv("SOUNDSLOP_PROVIDER_KEYS", raising=False)

    def test_generate_insufficient_tokens(self, client):
        token = register_and_login(client, "slop_broke")
        resp = client.post(
            "/api/soundslop/generate",
            json={"mode": "text", "prompt": "lo-fi beat", "duration_sec": 30},
            headers=_auth(token),
        )
        assert resp.status_code == 402
        assert resp.json()["detail"]["error"] == "insufficient_tokens"

    def test_generate_duration_validation(self, client, slop_user):
        token, user_id = slop_user
        _grant_tokens(user_id, 20)
        resp = client.post(
            "/api/soundslop/generate",
            json={"mode": "text", "prompt": "x", "duration_sec": 9999},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_generate_fails_and_refunds_without_provider(self, client, slop_user):
        token, user_id = slop_user
        _grant_tokens(user_id, token_service.cost_per_generation())
        balance_before = client.get(
            "/api/tokens/balance", headers=_auth(token)
        ).json()["balance"]

        resp = client.post(
            "/api/soundslop/generate",
            json={
                "mode": "text",
                "prompt": "aggressive phonk drift",
                "duration_sec": 30,
            },
            headers=_auth(token),
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        # Списание произошло сразу
        assert resp.json()["balance"] == balance_before - 10

        # TestClient синхронно выполняет BackgroundTasks: без ключей
        # провайдера job падает, токены возвращаются.
        job = client.get(f"/api/soundslop/jobs/{job_id}", headers=_auth(token))
        assert job.status_code == 200
        data = job.json()
        assert data["status"] == "failed"
        assert data["error"]

        balance_after = client.get(
            "/api/tokens/balance", headers=_auth(token)
        ).json()["balance"]
        assert balance_after == balance_before

    def test_jobs_list_only_own(self, client, slop_user):
        token, _ = slop_user
        other = register_and_login(client, "slop_other")
        resp = client.get("/api/soundslop/jobs", headers=_auth(other))
        assert resp.status_code == 200
        assert resp.json() == []

        resp = client.get("/api/soundslop/jobs", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
