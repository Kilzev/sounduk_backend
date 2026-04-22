# Sounduk API - Контекст проекта

**Это отправная точка для ознакомления с проектом FastAPI "Sounduk API" — облачное хранилище музыки с поддержкой Flutter.**

## 📚 Структура документации

| Файл | Назначение |
|------|-----------|
| **[backend_logic.md](backend_logic.md)** | Принятые стили кодирования, архитектурные решения, паттерны |
| **[db_schema.md](db_schema.md)** | Структура БД, таблицы, связи (relationships), ключи |
| **[system_map.md](system_map.md)** | Карта всех эндпоинтов, middleware, сервисов и их расположение |
| **[task_log.md](task_log.md)** | История изменений API и статусы текущих задач |

## 🔧 Скрипты для рутины

Папка `scripts/` содержит:
- `run_dev.sh` — запуск dev-сервера с reload
- `full_migrate.sh` — (планируется при переходе на Alembic)
- `test_coverage.sh` — запуск pytest с отчетом о покрытии

## 🚀 Быстрый старт

```bash
# Запуск dev-сервера
./context/scripts/run_dev.sh

# Запуск тестов
./context/scripts/test_coverage.sh

# Просмотр docs
# Откройте http://localhost:8000/docs
```

## 📋 Главные роуты

- `GET /` — health check
- `POST /api/auth/register` — регистрация
- `POST /api/auth/login` — вход
- `GET /api/users/me` — профиль текущего пользователя
- `GET/POST /api/tracks` — загрузка и получение треков
- `GET/POST /api/albums` — работа с альбомами
- `POST /api/payments/create` — создание платежа (YooKassa)
- `GET/POST /api/admin/users` — админка

## 🗄️ Интеграции

- **S3 (boto3)** — хранение файлов (covers, tracks)
- **YooKassa** — платежи (подписки)
- **SQLite** — БД (автоматическое создание таблиц при старте)
- **CORS** — открыто для Flutter-приложения

## ⚙️ Ключевые конфигурации

- **Async везде** — все хендлеры асинхронные
- **Dependency Injection** — `get_db()` как зависимость
- **Pydantic v2** — валидация через `BaseModel`
- **Rate limiting** — по IP для регистрации (макс 3 за 24h)
- **Периодический бэкап БД** — каждый час в S3

---

**Начни с [backend_logic.md](backend_logic.md), затем переходи к [system_map.md](system_map.md) для полной картины.**
