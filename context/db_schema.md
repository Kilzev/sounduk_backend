# Структура базы данных

## 🗄️ Обзор

- **Тип:** SQLite (файл `database.db`)
- **ORM:** SQLAlchemy 2.0
- **Синтаксис:** `Mapped`, `mapped_column`
- **Миграции:** Текущая система = `Base.metadata.create_all()` (неавтоматическая)

## 📋 Таблицы и их поля

### 1. **users** — Пользователи

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR UNIQUE NOT NULL,
    email VARCHAR UNIQUE NOT NULL,
    hashed_password VARCHAR NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Email-верификация
    is_verified BOOLEAN DEFAULT FALSE,
    verification_code VARCHAR NULL,
    code_sent_at DATETIME NULL,
    
    -- Админка
    is_admin BOOLEAN DEFAULT FALSE,
    is_premium BOOLEAN DEFAULT FALSE,
    premium_expires_at DATETIME NULL,
    
    -- Хранилище
    storage_limit BIGINT DEFAULT 1073741824,  -- 1 GB
    is_restricted BOOLEAN DEFAULT FALSE,      -- блокировка пользователя
    allow_youtube_import BOOLEAN DEFAULT FALSE -- per-account YouTube / link import
);
```

**Связи:**
- ← `tracks.user_id` (One-to-Many)
- ← `payments.user_id` (One-to-Many)
- ← `albums.user_id` (One-to-Many)

**Computed:**
- `storage_used` — sum(`tracks.file_size`) для всех треков пользователя

---

### 2. **tracks** — Музыкальные файлы

```sql
CREATE TABLE tracks (
    id VARCHAR PRIMARY KEY,                    -- UUID
    user_id INTEGER NOT NULL FOREIGN KEY,
    title VARCHAR NOT NULL,
    artist VARCHAR NOT NULL,
    album VARCHAR NULL,
    duration INTEGER NOT NULL,                 -- секунды
    file_path VARCHAR NOT NULL,                -- путь в S3 или локально
    file_size INTEGER NOT NULL,                -- байты (для лимита хранилища)
    cover_path VARCHAR NULL,                   -- путь к обложке трека
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Связи:**
- `user_id` → `users.id` (Many-to-One)
- ← `albums.track_ids` (JSON array reference)

**Ключевые индексы:**
- `(id)` PRIMARY KEY
- `(user_id)` для быстрого поиска по пользователю

---

### 3. **albums** — Альбомы

```sql
CREATE TABLE albums (
    id VARCHAR PRIMARY KEY,                    -- UUID
    user_id INTEGER PRIMARY KEY FOREIGN KEY,
    title VARCHAR NOT NULL,
    description TEXT NULL,
    cover_art BLOB NULL,                       -- обложка альбома (бинарные данные)
    track_ids JSON DEFAULT [],                 -- массив ID треков: ["id1", "id2"]
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

**Связи:**
- `user_id` → `users.id` (Many-to-One)
- `track_ids[]` → `tracks.id` (JSON reference)

**Примечание:** `track_ids` хранится как JSON массив, связь через значения, не через фк.

---

### 4. **payments** — Платежи (YooKassa)

```sql
CREATE TABLE payments (
    id VARCHAR PRIMARY KEY,                    -- YooKassa payment_id
    user_id INTEGER NOT NULL FOREIGN KEY,
    product_id VARCHAR NOT NULL,               -- товар (подписка, хранилище)
    amount FLOAT NOT NULL,                     -- сумма (рубли)
    currency VARCHAR DEFAULT 'RUB',
    status VARCHAR DEFAULT 'pending',          -- pending, succeeded, failed, cancelled
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Связи:**
- `user_id` → `users.id` (Many-to-One)

**Статусы:**
- `pending` — ожидание подтверждения
- `succeeded` — успешно
- `failed` — ошибка
- `cancelled` — отменен

---

### 5. **registration_limit** — Rate limiting по IP

```sql
CREATE TABLE registration_limit (
    id INTEGER PRIMARY KEY,
    ip_address VARCHAR UNIQUE NOT NULL,
    registrations_count INTEGER DEFAULT 0,
    first_registration_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Назначение:** Защита от спама регистраций (макс 3 за 24h с одного IP)

---

## 🔗 Граф связей

```
┌─────────────────────────────────────┐
│           USERS                      │ ◄─────┐
├─────────────────────────────────────┤       │
│ id (PK)                             │       │
│ username, email                     │       │
│ is_premium, premium_expires_at      │       │
│ storage_limit, is_restricted        │       │
│ allow_youtube_import                │       │
│ verification fields...              │       │
└─────────────────────────────────────┘       │
       │                                       │
       │ (One-to-Many)                        │
       │                                       │
       ├──► TRACKS ──────────────────────────┤
       │    (id, user_id, title, file_size)  │
       │    (cover_path)                     │
       │                                      │
       ├──► ALBUMS ───────────────────────────┤
       │    (id, user_id, track_ids[JSON])   │
       │                                      │
       └──► PAYMENTS ─────────────────────────┤
            (id, user_id, amount, status)    │
            (YooKassa payment_id)             │
```

## 📊 Примеры запросов

### Получить все треки пользователя
```sql
SELECT * FROM tracks WHERE user_id = ?;
```

### Получить альбом со всеми треками
```sql
SELECT a.*, GROUP_CONCAT(t.title) as track_titles
FROM albums a
JOIN tracks t ON a.track_ids LIKE '%' || t.id || '%'
WHERE a.user_id = ?;
```

### Получить использованное хранилище пользователя
```sql
SELECT SUM(file_size) as storage_used
FROM tracks WHERE user_id = ?;
```

### Проверить превышение лимита хранилища
```python
# В Python (ORM):
user = db.query(User).get(user_id)
if user.storage_used > user.storage_limit:
    # Ошибка: нет места
```

### Проверить успешные платежи
```sql
SELECT * FROM payments 
WHERE user_id = ? AND status = 'succeeded'
ORDER BY created_at DESC;
```

## ⚙️ Управление миграциями

### Текущий подход
- При старте приложения: `Base.metadata.create_all(bind=engine)`
- Таблицы создаются автоматически, если не существуют

### Когда переходить на Alembic
- Если нужны rolling updates (zero-downtime)
- Если есть сложные миграции данных
- Если проект выходит в продакшн

### Переход на Alembic
```bash
# Инициализация
alembic init alembic

# Создание миграции после изменения моделей
alembic revision --autogenerate -m "Add new column"

# Применение миграции
alembic upgrade head
```

## 🚨 Важные моменты

1. **track_ids в albums** хранится как JSON, а не через нормальную связь
   - ✅ Плюс: гибкость, быстрое удаление треков
   - ❌ Минус: JOINы сложнее, нет referential integrity

2. **storage_limit & storage_used** — `storage_used` вычисляется в runtime
   - Нет отдельной колонки, считается через sum()
   - Экономит место, но требует JOIN при каждом запросе

3. **verification_code** хранится в открытом виде
   - ✅ Текущее решение — OK для dev
   - ⚠️ Для продакшна: хешировать или удалять после верификации

4. **Premium expires** — ручная проверка в коде
   - Нет автоматического обратного отсчета
   - Проверяется в `get_current_user()` или в каждом запросе

---

**Начать: смотри миграции в `alembic/versions/` (когда будут добавлены) или текущую инициализацию в `main.py` lifespan.**
