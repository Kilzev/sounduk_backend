# 02 Risks And Debt

## Текущие риски

- YouTube-импорт через yt-dlp нагружает CPU/диск сервера; длинные плейлисты — только через jobs, лимит `YOUTUBE_IMPORT_MAX_ITEMS`.
- С VPS в РФ прямой доступ к YouTube блокируется; используется SOCKS-туннель `sounduk-yt-proxy` → `77.110.107.73`, `YTDLP_PROXY=socks5h://127.0.0.1:10801`.
- CORS сейчас открыт широко (`allow_origins=["*"]`) и требует ужесточения для production.
- Миграции БД не настроены через Alembic, используется `create_all()`.
- Нет контейнеризации и полностью формализованного CI/CD пайплайна.
- **Pydantic v2 silent ignore:** лишние/незадеплоенные поля request body не дают 422 — только 200 без эффекта. Держать `schemas.py` на проде в синхроне с репо (`cover_data` в `TrackUpdateRequest`, 2026-07-22).
- Cover endpoint auth-only — клиент не должен класть URL в unauthenticated image/media loaders.
- Частичный rsync без зависимостей (`auth_utils` и т.п.) может уронить `systemctl restart sounduk` — hotfix'ы только самодостаточными файлами.
- **Albums LWW:** `PUT/POST /api/albums` принимают клиентский `updatedAt`; если client < server — PUT не перетирает (возвращает текущий AlbumOut). Деплой `api/albums.py` обязателен вместе с клиентом.

## Технический долг

- Нормализовать хранение связей альбом-треки (сейчас `track_ids` в JSON).
- Усилить контроль rate limiting для чувствительных эндпоинтов (например, платежи).
- Провести ревизию секретов в конфиге и `.env`, хранить их только в защищенном хранилище.

## Примечание перед правками сети/платежей

Перед изменениями в `api/payments.py`, внешних HTTP вызовах и middleware проверять этот файл первым и фиксировать изменения в `change_log.md`.
