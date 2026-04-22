"""Тесты защиты админских эндпоинтов"""
import pytest
from conftest import TestingSessionLocal, register_and_login
import models


@pytest.fixture(autouse=True)
def clear_rate_limits():
    db = TestingSessionLocal()
    db.query(models.RegistrationLimit).delete()
    db.commit()
    db.close()


def _make_admin(email: str):
    """Делает пользователя админом напрямую через БД"""
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.email == email).first()
    user.is_admin = True
    db.commit()
    db.close()


def _get_email_for_username(username: str) -> str:
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.username == username).first()
    email = user.email if user else None
    db.close()
    return email


def test_non_admin_cannot_access_admin_endpoints(client):
    token = register_and_login(client, "regular_user_1")
    response = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_admin_can_list_users(client):
    token = register_and_login(client, "admin_list")
    _make_admin(_get_email_for_username("admin_list"))

    response = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_admin_cannot_demote_self(client):
    token = register_and_login(client, "admin_demote_self")
    _make_admin(_get_email_for_username("admin_demote_self"))

    # Ещё один админ, чтобы не сработала защита "последний админ"
    token2 = register_and_login(client, "admin_demote_other")
    _make_admin(_get_email_for_username("admin_demote_other"))

    # Получаем свой id
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    my_id = me["id"]

    response = client.patch(
        f"/api/admin/users/{my_id}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert "себя" in response.json()["detail"]


def test_admin_cannot_restrict_self(client):
    token = register_and_login(client, "admin_restrict_self")
    _make_admin(_get_email_for_username("admin_restrict_self"))

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    response = client.patch(
        f"/api/admin/users/{me['id']}",
        json={"is_restricted": True},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_admin_cannot_delete_self(client):
    token = register_and_login(client, "admin_delete_self")
    _make_admin(_get_email_for_username("admin_delete_self"))

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    response = client.delete(
        f"/api/admin/users/{me['id']}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_cannot_remove_last_admin(client):
    """Нельзя снять права с последнего админа (даже если это другой админ)"""
    # Очищаем всех админов
    db = TestingSessionLocal()
    db.query(models.User).filter(models.User.is_admin == True).update({"is_admin": False})
    db.commit()
    db.close()

    token = register_and_login(client, "lone_admin")
    _make_admin(_get_email_for_username("lone_admin"))

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()

    # Попытка снять с себя права — должна упасть (и на self-protect, и на last-admin)
    response = client.patch(
        f"/api/admin/users/{me['id']}",
        json={"is_admin": False},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_admin_can_grant_admin_to_another_user(client):
    # Создаём админа
    admin_token = register_and_login(client, "granter_admin")
    _make_admin(_get_email_for_username("granter_admin"))

    # Создаём обычного пользователя
    user_token = register_and_login(client, "target_user")
    target_id = client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}).json()["id"]

    # Назначаем админом
    response = client.patch(
        f"/api/admin/users/{target_id}",
        json={"is_admin": True},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["is_admin"] is True


def test_audit_log_records_actions(client):
    admin_token = register_and_login(client, "audit_admin")
    _make_admin(_get_email_for_username("audit_admin"))

    user_token = register_and_login(client, "audit_target")
    target_id = client.get("/api/auth/me", headers={"Authorization": f"Bearer {user_token}"}).json()["id"]

    # Делаем изменение
    client.patch(
        f"/api/admin/users/{target_id}",
        json={"is_premium": True},
        headers={"Authorization": f"Bearer {admin_token}"}
    )

    # Проверяем лог
    response = client.get(
        f"/api/admin/audit-log?target_user_id={target_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) >= 1
    assert logs[0]["action"] == "update_user"
    assert logs[0]["target_user_id"] == target_id
    assert "is_premium" in logs[0]["details"]


def test_regular_user_cannot_view_audit_log(client):
    token = register_and_login(client, "regular_user_2")
    response = client.get(
        "/api/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
