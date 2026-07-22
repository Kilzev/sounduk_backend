# Журнал задач и изменений API

**Последнее обновление:** 2026-07-21

---

## 📝 Статус текущих работ

### ✅ ЗАВЕРШЕНО (2026-07-21): Read-only audit tracks vs S3 + суточный бэкап БД

- ✅ Скрипт `context/scripts/audit_tracks_s3.py` (только SELECT + head_object)
- ✅ Прогон на проде `178.72.184.68`: 315 треков, **150 audio_missing**, 158 ok
- ✅ Отчёт: [`audit_tracks_s3_2026-07-21.md`](./audit_tracks_s3_2026-07-21.md)
- ✅ `db_backup.py`: интервал **24h**, prune timestamped > **90 дней** (latest не трогаем)
- ⏸️ **Remediation битых треков — НЕ делали** (нужен явный апрув). Объекты отсутствуют и в `uploads/`, и в `tracks/`.

### ✅ ЗАВЕРШЕНО (2026-06-04): YouTube → MP3 через RapidAPI youtube-mp310

- ✅ Клиент: `GET https://{YOUTUBE_MP3_HOST}{YOUTUBE_MP3_PATH}?url=<watch_url>` + заголовки RapidAPI
- ✅ Env: `RAPIDAPI_KEY`, `YOUTUBE_MP3_HOST`, `YOUTUBE_MP3_PATH` (`.env.example`, `check_env.py`)
- ✅ `load_dotenv()` в `main.py` / `api/tracks.py`
- ✅ Эндпоинты: `/api/tracks/import/youtube/track|playlist|jobs`
- ✅ Документация: `llm_client_app_info.md` §3.1.1
- ✅ Прод: переменные YouTube добавлены в `/var/www/sounduk_backend/.env`
- [ ] Перезапуск uvicorn на проде после выката `api/tracks.py` (если ещё не поднят)

---

### ✅ ЗАВЕРШЕНО (2026-06-04): Деплой на прод + SSH + инвентаризация сервера

**Сервер:** `185.76.242.73` (`root`), прод API: `https://api.sounduk.ru`

**Сделано:**

- ✅ SSH-ключ `~/.ssh/sounduk_cursor` → `authorized_keys`, вход без пароля
- ✅ Алиас `sounduk-prod` в `~/.ssh/config`
- ✅ Найден единственный боевой backend: `/var/www/sounduk_backend` (порт 8000)
- ✅ Очистка мусора на сервере и локально перед выкатом
- ✅ `rsync` кода (api, models, migrate_albums, tests, context)
- ✅ `migrate_albums.py` на проде — без новых изменений схемы
- ✅ Перезапуск uvicorn, smoke `GET /docs` → 200
- ✅ Обновлён `context/scripts/deploy.sh` (ключ, пути монорепо)
- ✅ Запись в `context/change_log.md`

**Удалено на сервере (дубликаты/мусор):**

- ✅ `/var/www/panop.sounduk.ru_backup_`
- ✅ `/etc/nginx/sites-enabled/sounduk_backend.bak.20260407174418`
- ✅ `._*` и старые `*.backup.*` в `/var/www/sounduk_backend`

**Не трогали (намеренно):**

- `/opt/driver_test_backend` — `/driver-api/` на :8010
- `/var/www/panop.sounduk.ru` — отдельный vhost `panop.sounduk.ru`

**Осталось / TODO после деплоя:**

- [ ] Убедиться на проде: `api/tracks.py` обновлён (после rsync проверить путь, не корень)
- [ ] Smoke YouTube: `POST /api/tracks/import/youtube/track` с тестовым URL
- [ ] Smoke: `PUT /api/albums/{id}` с `coverArt`, `GET /api/albums` на проде
- [ ] Smoke на мобильном клиенте (обложки альбомов, кириллица)
- [ ] `rsync`: исключить `database.db` и `uploads/` (см. change_log 2026-06-04)
- [ ] Настроить `systemd` unit `sounduk.service` (сейчас только `nohup`)
- [ ] Ротация root-пароля (был в git в `deploy.sh` / `ssh_info.md`)
- [ ] Убрать пароли из репозитория (`deploy.sh` уже без пароля)

**Детали:** `context/change_log.md` → раздел `2026-06-04`.

---

### ✅ ЗАВЕРШЕНО: S3 синхронизация БД

**Коммит:** [NEW] — refactor: Fix database S3 backup synchronization
- ✅ Исправлена логика `download_db_from_s3()` — теперь проверяет версии файлов
- ✅ Улучшена обработка ошибок в периодическом бэкапе
- ✅ Развернуто на боевой сервер (2026-04-22)
- ✅ **Результат:** 1000 бэкапов на S3, БД синхронизируется каждые 30 минут
- ✅ Диск сервера защищен от переполнения (БД в облаке)

**До исправления:**
- ❌ Бэкапы не работали правильно (локальная БД игнорировалась)
- ❌ 1000 старых бэкапов на S3 были неиспользованы
- ❌ БД занимала место на диске сервера

**После исправления:**
- ✅ БД 0.21 MB синхронизируется каждые 30 мин в S3
- ✅ При перезагрузке сервера БД восстанавливается автоматически
- ✅ Версионирование: последние 1000 версий хранятся в S3
- ✅ Диск сервера защищен (БД = только локальный кэш)

### ✅ Завершено (Latest commits)

**Коммит:** `771a521` — feat: Add albums endpoint, track covers, pricing update and freeze logic
- ✅ Новый эндпоинт: `POST /api/albums` (создание альбома)
- ✅ Новый эндпоинт: `GET /api/albums` (список альбомов)
- ✅ Поддержка обложек для альбомов (cover_art в BLOB)
- ✅ Новый эндпоинт: `POST /api/tracks/{track_id}/cover` (загрузка обложки трека)
- ✅ Логика замораживания (freeze logic) при превышении лимита хранилища

**Коммит:** `f737657` — feat: Add payments and users endpoints, S3 integration, tests and deployment docs
- ✅ YooKassa интеграция: `POST /api/payments/create`, вебхук
- ✅ Users endpoints: `GET /api/users/me`, `GET /api/users/storage`
- ✅ S3 интеграция (boto3): загрузка/удаление файлов, бэкап БД
- ✅ Основные тесты: `test_payments.py`, `test_users.py`

**Коммит:** `9e7a41d` — feat: Implement admin panel, user restrictions, storage limits and remove email
- ✅ Admin endpoints: `GET/PUT/DELETE /api/admin/users`
- ✅ Ограничение пользователей: `POST /api/admin/users/{user_id}/restrict`
- ✅ Система лимитов хранилища
- ✅ Email верификация (отправка кодов подтверждения)

---

## 📋 Текущие задачи

### 🔄 В разработке

**[2026-04-22] Создание infrastructure контекста**
- 📄 Создание `context/` папки с документацией
- 📄 Файлы: `index.md`, `backend_logic.md`, `db_schema.md`, `system_map.md`, `task_log.md`
- 📄 Скрипты: `scripts/run_dev.sh`, `test_coverage.sh`
- 📄 Создание `.clinerules` в корне

**[TODO] Миграция на Alembic**
- 🔲 Инициализация Alembic (`alembic init alembic`)
- 🔲 Создание начальной миграции
- 🔲 Удаление `Base.metadata.create_all()` из main.py
- 🔲 Обновление CI/CD (deployment docs)

**[TODO] Docker контейнеризация**
- 🔲 Dockerfile для приложения
- 🔲 docker-compose.yml с SQLite volume + environment vars
- 🔲 GitHub Actions для сборки/публикации образа

**[TODO] CI/CD Pipeline**
- 🔲 GitHub Actions для запуска тестов при push
- 🔲 Проверка покрытия (pytest-cov)
- 🔲 Linting (pylint, flake8)

---

## 🔍 Известные проблемы (Known Issues)

| ID | Описание | Статус | Приоритет |
|----|----------|--------|-----------|
| **KI-001** | CORS разрешен для всех origin'ов (`allow_origins=["*"]`) | 🔴 Open | High |
| **KI-002** | Нет Alembic миграций, используется `create_all()` | 🔴 Open | Medium |
| **KI-003** | Нет Docker контейнеризации | 🔴 Open | Medium |
| **KI-004** | Rate limiting только на регистрацию (нет на платежи) | 🔴 Open | Low |
| **KI-005** | Email-интеграция зависит от `.env` переменных | ⚠️ Review | Low |
| **KI-006** | ~~БД на сервере, не синхронизируется с S3~~ | ✅ FIXED | High |
| **KI-007** | API без systemd — перезапуск через `pkill`/`nohup`, риск 502 при деплое | 🔴 Open | High |
| **KI-008** | `rsync` деплой может затронуть `database.db` / `uploads/` если не исключить | ⚠️ Review | High |

**Решение KI-001 (CORS):**
```python
# CURRENT (dev):
allow_origins=["*"]

# PRODUCTION:
allow_origins=[
    "https://yourdomain.com",
    "https://app.yourdomain.com"
]
```

---

## 📊 История изменений API

### v1.0.0 (Current)

#### **Auth endpoints** (`api/auth.py`)
- `POST /api/auth/register` — регистрация с rate limiting по IP
- `POST /api/auth/login` — логин с JWT токеном
- `POST /api/auth/verify` — верификация email по коду
- `POST /api/auth/resend-code` — переотправка кода
- `POST /api/auth/forgot-password` — запрос на сброс пароля
- `POST /api/auth/reset-password` — сброс пароля по токену

#### **Tracks endpoints** (`api/tracks.py`)
- `GET /api/tracks` — список треков пользователя
- `POST /api/tracks` — загрузка трека (multipart/form-data)
- `GET /api/tracks/{track_id}` — информация о треке
- `DELETE /api/tracks/{track_id}` — удаление трека
- `GET /api/tracks/{track_id}/stream` — стриминг трека
- `POST /api/tracks/{track_id}/cover` — загрузка обложки

#### **Albums endpoints** (`api/albums.py`)
- `GET /api/albums` — список альбомов пользователя
- `POST /api/albums` — создание альбома
- `GET /api/albums/{album_id}` — информация об альбоме
- `PUT /api/albums/{album_id}` — редактирование альбома
- `DELETE /api/albums/{album_id}` — удаление альбома
- `POST /api/albums/{album_id}/tracks` — добавить трек в альбом
- `DELETE /api/albums/{album_id}/tracks/{track_id}` — удалить трек из альбома

#### **Users endpoints** (`api/users.py`)
- `GET /api/users/me` — профиль текущего пользователя
- `PUT /api/users/me` — обновление профиля
- `GET /api/users/storage` — информация о хранилище

#### **Payments endpoints** (`api/payments.py`)
- `POST /api/payments/create` — создание платежа (YooKassa)
- `GET /api/payments/status/{payment_id}` — статус платежа
- `POST /api/payments/webhook` — вебхук от YooKassa

#### **Admin endpoints** (`api/admin.py`)
- `GET /api/admin/users` — список всех пользователей
- `GET /api/admin/users/{user_id}` — информация о пользователе
- `PUT /api/admin/users/{user_id}` — редактирование пользователя
- `DELETE /api/admin/users/{user_id}` — удаление пользователя
- `POST /api/admin/users/{user_id}/restrict` — блокировка пользователя
- `POST /api/admin/users/{user_id}/unrestrict` — разблокировка пользователя
- `GET /api/admin/stats` — статистика приложения

---

## 🔄 Процесс обновления документации

Когда добавляешь новый эндпоинт:

1. **Создай функцию в `api/*.py`**
   ```python
   @router.post("/new-endpoint")
   async def new_endpoint_handler(data: SomeSchema = Body(), db: Session = Depends(get_db)):
       # Реализация
   ```

2. **Добавь Pydantic schema в `schemas.py`** (если требуется)
   ```python
   class SomeSchema(BaseModel):
       field: str
   ```

3. **Добавь запись в `system_map.md`** (таблица эндпоинтов)
   ```markdown
   | `POST` | `/api/new-endpoint` | `new_endpoint_handler()` | ✅ |
   ```

4. **Обновляй `task_log.md`** (эта таблица)
   ```markdown
   **[2026-04-22] Новый эндпоинт: /api/new-endpoint**
   - Функция: new_endpoint_handler()
   - Требует аутентификацию: ✅
   ```

5. **Коммит**
   ```bash
   git add .
   git commit -m "feat: Add new endpoint /api/new-endpoint"
   ```

---

## 📈 Метрики и KPI

### Performance
- Средний response time: **< 500ms**
- P95 latency (треки > 100MB): **< 2s**

### Reliability
- Uptime target: **99.5%**
- Error rate (4xx, 5xx): **< 0.5%**

### Usage
- Активные пользователи: TBD
- Средний размер трека: ~40MB
- Средний размер альбома: ~5-10 треков

---

## 🗓️ Дорожная карта (Roadmap)

### Q2 2026
- [x] MVP: Auth + Tracks + Payments
- [ ] Alembic миграции
- [ ] Docker контейнеризация
- [ ] GitHub Actions CI/CD

### Q3 2026
- [ ] Плейлисты (Playlists)
- [ ] Социальные функции (share, comments)
- [ ] Advanced search & filtering
- [ ] Mobile app push notifications

### Q4 2026
- [ ] Podcast support
- [ ] Recommendation engine (ML)
- [ ] Analytics dashboard
- [ ] High availability (PostgreSQL + Kubernetes)

---

## 📞 Контакты и ссылки

- **GitHub:** https://github.com/yourusername/sounduk_backend
- **Issues:** Используй GitHub Issues для трекинга багов
- **Documentation:** В папке `context/` (этот файл + others)
- **Dev Setup:** `./context/scripts/run_dev.sh`

---

**Последнее изменение:** 2026-06-04
