import pytest
import sys
import os

# Добавляем корневую директорию в PYTHONPATH, чтобы тесты видели модули
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
import api.tracks
import models
from pathlib import Path
from unittest.mock import patch

# Используем in-memory SQLite для тестов
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Счётчик для уникальных email в тестах
_email_counter = 0


def register_and_login(client, username, password="password123", verify=True):
    """Хелпер: регистрирует пользователя, верифицирует и логинит. Возвращает токен."""
    global _email_counter
    _email_counter += 1
    email = f"{username}_{_email_counter}@test.local"

    # Сбрасываем rate limit регистраций
    db = TestingSessionLocal()
    db.query(models.RegistrationLimit).delete()
    db.commit()
    db.close()

    reg = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password}
    )
    if reg.status_code != 201:
        # Fallback для случая если пользователь уже существует — логинимся
        login = client.post(
            "/api/auth/login",
            json={"email": email, "password": password}
        )
        assert login.status_code == 200, f"Register failed ({reg.status_code}: {reg.text}), login also failed ({login.status_code})"
        return login.json()["access_token"]

    if verify:
        db = TestingSessionLocal()
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.is_verified = True
            db.commit()
        db.close()

    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


@pytest.fixture(scope="module", autouse=True)
def mock_upload_dir(tmp_path_factory):
    """Используем временную папку для загрузок"""
    temp_dir = tmp_path_factory.mktemp("test_uploads")
    original_upload_dir = api.tracks.UPLOAD_DIR
    api.tracks.UPLOAD_DIR = temp_dir
    yield temp_dir
    api.tracks.UPLOAD_DIR = original_upload_dir

@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Мокаем отправку email (чтобы тесты не ждали SMTP timeout)
    with patch("api.auth.send_verification_email", return_value=True), \
         patch("api.auth.send_password_reset_email", return_value=True):
        with TestClient(app) as c:
            yield c

    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="module")
def test_user_token(client):
    """Регистрирует верифицированного пользователя и возвращает токен"""
    return register_and_login(client, "test_user")

@pytest.fixture(scope="module")
def admin_token(client):
    """Регистрирует админа и возвращает токен"""
    token = register_and_login(client, "admin_user", "admin123")

    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.username == "admin_user").first()
    if user:
        user.is_admin = True
        db.commit()
    db.close()

    return token
