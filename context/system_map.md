# Карта системы (System Map)

## 🗺️ Обзор архитектуры

```
┌──────────────────────────────────────────────────────────────┐
│                      main.py (Entry Point)                   │
│  ┌─ lifespan context                                        │
│  │  ├─ Startup: download_db_from_s3, create_all, backup     │
│  │  └─ Shutdown: backup, upload_db_to_s3                    │
│  └─ CORS middleware (allow all)                             │
└──────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌─────────┐  ┌─────────┐  ┌─────────┐
         │ api/    │  │ schemas │  │ database│
         │ routers │  │ (Pydantic)│ (Session)│
         └─────────┘  └─────────┘  └─────────┘
              │
    ┌─────────┼─────────┬─────────┬──────────┐
    ▼         ▼         ▼         ▼          ▼
  auth.py  tracks.py albums.py users.py  admin.py  payments.py
```

---

## 📍 Эндпоинты по модулям

### 1. **api/auth.py** — Аутентификация

| Метод | Эндпоинт | Функция | Аутентификация |
|-------|----------|---------|---|
| `POST` | `/api/auth/register` | `register()` | ❌ |
| `POST` | `/api/auth/login` | `login()` | ❌ |
| `POST` | `/api/auth/verify` | `verify_email()` | ❌ |
| `POST` | `/api/auth/resend-code` | `resend_verification_code()` | ❌ |
| `POST` | `/api/auth/forgot-password` | `forgot_password()` | ❌ |
| `POST` | `/api/auth/reset-password` | `reset_password()` | ❌ |

**Используемые утилиты:**
- `auth_utils.py` — `hash_password()`, `verify_password()`, `create_access_token()`
- `email_utils.py` — `send_verification_email()`, `send_password_reset_email()`
- `models.py` — `User`, `RegistrationLimit`

---

### 2. **api/tracks.py** — Управление музыкой

| Метод | Эндпоинт | Функция | Аутентификация |
|-------|----------|---------|---|
| `GET` | `/api/tracks` | `get_tracks()` | ✅ |
| `POST` | `/api/tracks` | `upload_track()` | ✅ |
| `GET` | `/api/tracks/{track_id}` | `get_track()` | ✅ |
| `DELETE` | `/api/tracks/{track_id}` | `delete_track()` | ✅ |
| `GET` | `/api/tracks/{track_id}/stream` | `stream_track()` | ✅ |
| `POST` | `/api/tracks/{track_id}/cover` | `upload_cover()` | ✅ |

**Используемые утилиты:**
- `s3_utils.py` — загрузка/удаление из S3
- `mutagen` — извлечение метаданных (title, artist, duration)
- `models.py` — `Track`

**Ключевые процессы:**
- При загрузке: парсинг метаданных → сохранение в S3 → запись в БД
- При удалении: удаление из S3 → обновление БД
- Проверка лимита хранилища перед загрузкой

---

### 3. **api/albums.py** — Альбомы

| Метод | Эндпоинт | Функция | Аутентификация |
|-------|----------|---------|---|
| `GET` | `/api/albums` | `get_albums()` | ✅ |
| `POST` | `/api/albums` | `create_album()` | ✅ |
| `GET` | `/api/albums/{album_id}` | `get_album()` | ✅ |
| `PUT` | `/api/albums/{album_id}` | `update_album()` | ✅ |
| `DELETE` | `/api/albums/{album_id}` | `delete_album()` | ✅ |
| `POST` | `/api/albums/{album_id}/tracks` | `add_track_to_album()` | ✅ |
| `DELETE` | `/api/albums/{album_id}/tracks/{track_id}` | `remove_track_from_album()` | ✅ |

**Используемые модели:**
- `models.py` — `Album`, `Track`
- `schemas.py` — `AlbumCreate`, `AlbumResponse`

**Ключевые процессы:**
- `track_ids` хранится как JSON массив в `albums.track_ids`
- При удалении альбома: не удаляются сами треки, только ссылка

---

### 4. **api/users.py** — Профиль пользователя

| Метод | Эндпоинт | Функция | Аутентификация |
|-------|----------|---------|---|
| `GET` | `/api/users/me` | `get_current_user()` | ✅ |
| `PUT` | `/api/users/me` | `update_profile()` | ✅ |
| `GET` | `/api/users/storage` | `get_storage_info()` | ✅ |

**Возвращаемые данные:**
- Профиль: username, email, is_premium, storage_used, storage_limit
- Storage info: используемое место, лимит, процент занятости

---

### 5. **api/payments.py** — Платежи

| Метод | Эндпоинт | Функция | Аутентификация |
|-------|----------|---------|---|
| `POST` | `/api/payments/create` | `create_payment()` | ✅ |
| `GET` | `/api/payments/status/{payment_id}` | `get_payment_status()` | ✅ |
| `POST` | `/api/payments/webhook` | `yookassa_webhook()` | ❌ |

**Интеграция:** YooKassa (Yandex Kassa)
- При создании: отправка запроса в YooKassa API, получение `confirmation_url`
- При вебхуке: обновление статуса платежа в БД (`succeeded` → обновление `is_premium`, `premium_expires_at`)

**Используемые модели:**
- `models.py` — `Payment`
- `yookassa` SDK

---

### 6. **api/admin.py** — Админ-панель

| Метод | Эндпоинт | Функция | Аутентификация | Роль |
|-------|----------|---------|---|---|
| `GET` | `/api/admin/users` | `get_all_users()` | ✅ | Admin |
| `GET` | `/api/admin/users/{user_id}` | `get_user()` | ✅ | Admin |
| `PUT` | `/api/admin/users/{user_id}` | `update_user()` | ✅ | Admin |
| `DELETE` | `/api/admin/users/{user_id}` | `delete_user()` | ✅ | Admin |
| `POST` | `/api/admin/users/{user_id}/restrict` | `restrict_user()` | ✅ | Admin |
| `POST` | `/api/admin/users/{user_id}/unrestrict` | `unrestrict_user()` | ✅ | Admin |
| `GET` | `/api/admin/stats` | `get_stats()` | ✅ | Admin |

**Проверка прав:** `get_current_user()` → проверка `is_admin`

---

## 🔐 Middleware & Auth Flow

```
┌─────────────────────────────────────┐
│      Incoming Request               │
└────────────────┬────────────────────┘
                 │
        ┌────────▼────────┐
        │ CORS Middleware │
        └────────┬────────┘
                 │
        ┌────────▼─────────────────────┐
        │ Route Matching               │
        └────────┬─────────────────────┘
                 │
        ┌────────▼──────────────────────────────┐
        │ Dependency: get_current_user()        │
        │ (если ✅ в таблице эндпоинтов)       │
        │ ├─ Извлечение JWT из headers         │
        │ ├─ Проверка валидности (auth_utils)  │
        │ ├─ Загрузка user из БД               │
        │ └─ Проверка is_admin (если нужна)   │
        └────────┬──────────────────────────────┘
                 │
        ┌────────▼──────────────────┐
        │ Route Handler             │
        │ (api/*.py функция)        │
        └────────┬──────────────────┘
                 │
        ┌────────▼──────────────────┐
        │ Business Logic            │
        │ (auth_utils, s3_utils)    │
        └────────┬──────────────────┘
                 │
        ┌────────▼──────────────────┐
        │ Database Operations       │
        │ (get_db() session)        │
        └────────┬──────────────────┘
                 │
        ┌────────▼──────────────────┐
        │ Response (Pydantic)       │
        │ (schemas.py)              │
        └──────────────────────────┘
```

---

## 🗂️ Файловая структура

```
sounduk_backend/
├── main.py                    # Entry point, app config, lifespan
├── database.py                # SQLAlchemy engine, SessionLocal, get_db()
├── models.py                  # ORM модели (User, Track, Album, Payment, etc.)
├── schemas.py                 # Pydantic валидация (DTO)
├── auth_utils.py              # JWT, хеширование паролей
├── email_utils.py             # Отправка email (verify, reset password)
├── s3_utils.py                # Загрузка/удаление файлов в S3
├── db_backup.py               # Периодический бэкап БД в S3
├── requirements.txt           # Зависимости
├── .env                       # Секреты (SMTP, AWS, YooKassa)
├── database.db                # SQLite файл БД
├── uploads/                   # Временное хранилище (локально)
├── api/
│   ├── __init__.py
│   ├── auth.py                # POST /register, /login, /verify, etc.
│   ├── tracks.py              # GET/POST /tracks, /stream, /cover
│   ├── albums.py              # GET/POST /albums, /albums/{id}/tracks
│   ├── users.py               # GET /me, /storage, PUT /me
│   ├── payments.py            # POST /create, /webhook
│   └── admin.py               # GET/PUT /users, /stats, /restrict
└── test/
    ├── conftest.py            # pytest fixtures
    ├── test_auth.py
    ├── test_tracks.py
    ├── test_albums.py
    ├── test_users.py
    ├── test_payments.py
    └── test_admin.py
```

---

## 🔄 Ключевые потоки данных

### Регистрация & Email верификация
```
1. POST /api/auth/register
   ├─ Валидация (Pydantic)
   ├─ Проверка rate limit (IP)
   ├─ Hash пароля (argon2)
   ├─ Создание User в БД
   ├─ Генерация verification_code
   ├─ Отправка email (SMTP)
   └─ Ответ: 201 Created

2. POST /api/auth/verify
   ├─ Проверка кода (TTL = 10 минут)
   ├─ Обновление is_verified = True
   └─ Ответ: 200 OK
```

### Загрузка трека
```
1. POST /api/tracks (multipart/form-data)
   ├─ Аутентификация (JWT)
   ├─ Проверка лимита хранилища
   ├─ Парсинг метаданных (mutagen)
   ├─ Загрузка в S3
   ├─ Запись в БД (models.Track)
   └─ Ответ: 200 OK + track_id

2. GET /api/tracks/{track_id}/stream
   ├─ Аутентификация
   ├─ Проверка прав (owner == current_user)
   ├─ Генерация presigned URL в S3
   └─ Redirect к S3 (или stream)
```

### Платеж (Premium подписка)
```
1. POST /api/payments/create
   ├─ Аутентификация
   ├─ Создание Order в YooKassa API
   ├─ Сохранение платежа в БД (status='pending')
   └─ Ответ: confirmation_url для клиента

2. POST /api/payments/webhook (YooKassa → Server)
   ├─ Проверка подписи (security)
   ├─ Обновление платежа (status='succeeded')
   ├─ Обновление User (is_premium=True, premium_expires_at)
   └─ Ответ: 200 OK

3. GET /api/payments/status/{payment_id}
   ├─ Аутентификация
   └─ Возврат статуса из БД
```

---

## 🌐 Интеграции

| Сервис | Использование | Конфиг |
|--------|---------------|--------|
| **S3 (AWS)** | Хранение файлов, бэкап БД | `.env`: AWS_ACCESS_KEY, AWS_SECRET_KEY |
| **YooKassa** | Платежи | `.env`: YOOKASSA_SHOP_ID, YOOKASSA_API_KEY |
| **SMTP** | Email верификация | `.env`: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD |
| **SQLite** | Основная БД | `database.db` (локально) |

---

## 📊 Поток здоровья (Health Check)

```
GET / → { "message": "Sounduk API работает!", "docs": "/docs" }
```

**Для полной docs:** `GET /docs` (Swagger UI), `GET/redoc` (ReDoc)

---

## ⚙️ Периодические задачи (Lifespan)

```python
# На STARTUP
✓ download_db_from_s3()          # Восстановление БД из S3
✓ Base.metadata.create_all()     # Создание таблиц
✓ start_periodic_backup()        # Запуск фоновой задачи (раз в сутки + prune >90d)

# На SHUTDOWN
✓ stop_periodic_backup()         # Остановка задачи
✓ upload_db_to_s3()              # Финальный бэкап
```

---

**Для добавления нового эндпоинта:**
1. Создай функцию в `api/*.py`
2. Обнови `system_map.md` (добавь в таблицу эндпоинтов)
3. Обнови `task_log.md` (добавь запись о изменении)
4. Добавь Pydantic schema в `schemas.py` если требуется
