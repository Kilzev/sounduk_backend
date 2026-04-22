# Принятый стиль и архитектурные решения

## 📐 Архитектурные паттерны

### FastAPI & Dependency Injection
- **Паттерн:** FastAPI с `Depends()` для внедрения зависимостей
- **Пример:** `def some_handler(db: Session = Depends(get_db)):`
- **Почему:** Чистота, тестируемость, автоматическое управление ресурсами

### Асинхронность
- **Правило:** ВСЕ хендлеры и сервисные функции асинхронные (`async def`)
- **Исключения:** Вспомогательные функции типа хеширования паролей (sync)
- **Пример:** `async def get_tracks(skip: int = 0, db: Session = Depends(get_db))`

### Валидация данных
- **Используем:** Pydantic v2 (`BaseModel` из pydantic)
- **Правило:** ВСЕ входные данные валидируются через Pydantic schemas
- **Локация:** `schemas.py` содержит все DTO (Data Transfer Objects)

### Слои приложения

```
main.py                    # Точка входа, конфиг app, lifespan
├─ api/                    # LAYER 1: Роутеры (HTTP endpoints)
│  ├─ auth.py
│  ├─ tracks.py
│  ├─ albums.py
│  ├─ users.py
│  ├─ payments.py
│  └─ admin.py
├─ models.py               # LAYER 2: ORM модели (SQLAlchemy)
├─ schemas.py              # LAYER 3: Pydantic валидация (DTO)
├─ database.py             # LAYER 4: БД конфиг + session manager
├─ auth_utils.py           # LAYER 5: Бизнес-логика (JWT, хеширование)
├─ email_utils.py          # LAYER 5: Email сервис
├─ db_backup.py            # LAYER 5: S3 бэкап сервис
└─ s3_utils.py             # LAYER 5: S3 утилиты
```

**Иерархия вызовов:**
1. Роут (api/\*.py) получает запрос
2. Валидирует через Pydantic (schemas.py)
3. Вызывает бизнес-логику (auth_utils, email_utils, etc.)
4. Работает с ORM (models.py) через session (database.py)
5. Возвращает Pydantic response

### Управление сессией БД
- **Паттерн:** `get_db()` как Dependency в FastAPI
- **Локация:** `database.py`
- **Правило:** Каждый эндпоинт получает свежую сессию, закрывается автоматически

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

## 🔐 Безопасность

### Аутентификация
- **JWT Token** через `python-jose`
- **Хеширование:** Argon2 через passlib
- **Функция:** `create_access_token()`, `verify_password()` в `auth_utils.py`

### Rate Limiting
- **Где:** На регистрацию (по IP)
- **Лимит:** 3 регистрации за 24 часа
- **Таблица:** `RegistrationLimit` (tracks по IP)

### CORS
- **Конфиг:** Открыто для Flutter (`allow_origins=["*"]`)
- **Причина:** Мобильное приложение требует доступа

## 💾 База данных

### Конфигурация
- **Тип:** SQLite (файл `database.db`)
- **ORM:** SQLAlchemy 2.0
- **Миграции:** Нет (используется `Base.metadata.create_all()`)
- **Синтаксис:** Новый (`Mapped`, `mapped_column`)

### Таблицы
- `users` — пользователи, хранилище, премиум, админка
- `tracks` — музыкальные файлы, covers, метаданные
- `albums` — альбомы, обложки
- `payments` — платежи YooKassa
- `registration_limit` — rate limiting по IP

## 🔌 Интеграции

### S3 (boto3)
- **Файлы:** Tracks, covers
- **Бэкап:** Периодический бэкап `database.db` в S3
- **Функции:** `upload_db_to_s3()`, `download_db_from_s3()` в `db_backup.py`
- **Интервал:** Каждый час (в lifespan)

### YooKassa (Yandex.Kassa)
- **Что:** Обработка платежей для подписок
- **Модель:** Payment table, платежи хранятся с `status` (pending/succeeded)

### Email
- **Используется для:** Верификация аккаунтов, сброс пароля
- **Функции:** `send_verification_email()`, `send_password_reset_email()` в `email_utils.py`

## 📦 Зависимости (key)

```
fastapi==0.115.0              # Web framework
uvicorn[standard]==0.32.0     # ASGI server
sqlalchemy==2.0.36            # ORM
pydantic>=2.9.2               # Validation
python-jose[cryptography]     # JWT
passlib, argon2-cffi          # Password hashing
boto3                         # S3
yookassa                      # Payments
pytest                        # Testing
httpx                         # HTTP client (tests)
python-dotenv                 # Environment vars
```

## 🧪 Тестирование

- **Framework:** pytest
- **Локация:** `test/` папка
- **Паттерн:** conftest.py для фикстур, отдельные файлы для модулей
- **Запуск:** `pytest` или `./context/scripts/test_coverage.sh`

## ⚠️ Техдолг и ограничения

1. **Нет Alembic миграций** — используется `create_all()`, не масштабируется
   - **План:** Переносить на Alembic при росте проекта
   
2. **Нет Docker** — нужен для продакшена
   - **План:** Добавить Dockerfile при деплойменте

3. **CORS открыт полностью** — нужно ограничить для продакшена
   - **Текущий:** `allow_origins=["*"]` для разработки
   - **Продакшн:** Указать конкретные origin'ы

4. **Email-интеграция зависит от переменных окружения**
   - **Файл:** `.env` с SMTP-конфигурацией

---

**Ключевой принцип:** Простота, асинхронность везде, валидация через Pydantic, dependency injection через FastAPI.
