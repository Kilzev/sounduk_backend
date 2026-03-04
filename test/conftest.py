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
from pathlib import Path

# Используем in-memory SQLite для тестов
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="module", autouse=True)
def mock_upload_dir(tmp_path_factory):
    """Используем временную папку для загрузок"""
    temp_dir = tmp_path_factory.mktemp("test_uploads")
    original_upload_dir = api.tracks.UPLOAD_DIR
    api.tracks.UPLOAD_DIR = temp_dir
    yield temp_dir
    # Возвращаем старое значение (хотя процесс завершится)
    api.tracks.UPLOAD_DIR = original_upload_dir

@pytest.fixture(scope="module")
def client():
    # Создаем таблицы
    Base.metadata.create_all(bind=engine)
    
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as c:
        yield c
    
    # Удаляем таблицы после тестов (хотя in-memory и так очистится)
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="module")
def test_user_token(client):
    """Регистрирует пользователя и возвращает токен"""
    # 1. Register
    reg_data = {"username": "test_user", "password": "password123"}
    response = client.post("/api/auth/register", json=reg_data)
    if response.status_code != 201:
        # User already exists in previous test potentially? But scope module rebuilds DB.
        pass
        
    # 2. Login
    login_data = {"username": "test_user", "password": "password123"}
    response = client.post("/api/auth/login", json=login_data)
    assert response.status_code == 200
    token = response.json()["access_token"]
    return token

@pytest.fixture(scope="module")
def admin_token(client):
    """Регистрирует админа и возвращает токен"""
    reg_data = {"username": "admin_user", "password": "admin123"}
    client.post("/api/auth/register", json=reg_data)
    
    # Нужно сделать его админом вручную через БД, но пока проверим регистрацию
    # Login
    response = client.post("/api/auth/login", json=reg_data)
    token = response.json()["access_token"]
    
    # TODO: Set is_admin=True via DB session directly if needed for admin tests
    return token
