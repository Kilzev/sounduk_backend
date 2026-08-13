# Change Log

## 2026-08-12 — Per-account YouTube import flag

- `users.allow_youtube_import` (default false); в `UserResponse` / admin PATCH.
- Import youtube/direct Depends → `get_verified_youtube_import_user` (не Premium).
- Миграция: `add_cols.py` → `allow_youtube_import BOOLEAN DEFAULT 0`.

## 2026-08-11 — DB backup retention 7 days (<10MB)

- One-shot prune: deleted **5418** old `backups/*`, then densified last week to
  **1 snapshot/day** → backups **9 objs / 8.7 MiB** (was ~3.7 GiB).
- `BACKUP_RETENTION_DAYS=7`; `upload_db_to_s3`: (1) prune week+ densify (2) save
  latest + timestamped. Bucket total ~3.7 GiB (mostly user audio).

## 2026-08-11 — Poisoned S3 latest: stop old host + restore + harden

- **Причина:** старый API `185.76.242.73` всё ещё заливал БД от 21.07 (343 трека)
  каждые 30 мин в тот же бакет `sounduk` → `database_latest.db`. Emelda при
  рестарте 10.08 сравнивала S3 `LastModified` (время upload) с mtime local и
  затирала живую БД.
- **Этап 1:** `systemctl stop|disable sounduk` на `185.76.242.73`; orphan uvicorn убит.
- **Этап 2:** на `178.72.184.68` восстановлен `backups/database_20260810_103220.db`
  → tracks=547 / Ilya=367 / users=14 / albums=8; pre-copy
  `database.db.pre_restore_poisoned_20260811_100421`; `upload_db_to_s3` latest.
- **Этап 3:** `db_backup.download_db_from_s3` — если local существует, auto-restore
  **запрещён** (только fill при отсутствии файла). Деплой `db_backup.py` на emelda;
  лог: `keep local; auto-restore disabled when local exists`.

## 2026-08-10 — Play RU payment geo gate

- Deployed `api/payments.py` + `schemas.py` to `178.72.184.68`.
- `PAYMENTS_GEO_ENFORCE=true`, `PAYMENTS_ALLOWED_COUNTRIES=RU` in prod `.env`.
- `GET /api/payments/eligibility`; `POST /create` → 403 `payment_region_unavailable` вне allowlist (fail closed on lookup miss).
- Country via ip-api.com (or `PAYMENTS_GEO_FORCE_COUNTRY` for tests).
- Backups: `payments.py.backup.*`, `schemas.py.backup.*`.
- Smoke: docs 200; eligibility US deny / RU allow; unauth eligibility 401; service active.
- Tests: `test/test_payments.py` — 7 passed.

## 2026-08-05 — Restore fuller DB (Ilya ~367 tracks)

- User reported Ilya ~400 tracks; S3 max found: `backups/database_20260804_122608.db` → **Ilya=367**, total **547**, users 14, albums 8.
- Replaced live DB; pre-copy `database.db.pre_restore_ilya400_20260805_123156`.
- migrate_albums.py + password reset `kny_iv@mail.ru` → `d1k2u3c4SS!!`.
- Uploaded restored DB to S3 latest via `upload_db_to_s3` (avoid clobber on restart).
- Smoke: login/me 200, docs 200, service active.

## 2026-08-05 — Restore DB from S3 + password reset

- Live DB had **203** tracks (truncated). Restored `backups/database_latest.db` from Selectel → **343** tracks / 13 users / 9 albums.
- Pre-restore copy: `database.db.pre_restore_20260805_122652`.
- Re-ran `migrate_albums.py` (noop mostly; cumulative_bytes backfill for 4 users).
- Reset password for `kny_iv@mail.ru` (`admin`) to value from `ssh_info.md` (`d1k2u3c4SS!!`).
- Smoke: login OK; `POST /api/payments/mock` → 404; `/docs` 200.
- Note: larger S3 snapshot `backups/database_20260804_122608.db` has **547** tracks (Ilya 367) — not applied; ask if needed.

## 2026-08-05 — Payment mock gate + schema migrate on prod

- Host: `178.72.184.68` (`emelda`), path `/var/www/sounduk_backend`.
- Deployed `api/payments.py`: `_payment_mock_enabled()` / `ENABLE_PAYMENT_MOCK` (unset on prod).
- Backup: `api/payments.py.backup.20260805_121629`.
- Smoke: `POST /api/payments/mock` authenticated → **404**; `/docs` 200; `sounduk.service` active.
- Found schema drift after restart: `users.library_revision` missing → auth 500.
- Ran `python migrate_albums.py` after DB backup `database.db.backup_pre_library_revision_20260805_122034`.
  - Added: `users.library_revision`, `albums.cover_path`, `tracks.cumulative_bytes` (+ backfill 3 users).
- Restart `systemctl restart sounduk` → mock 404 OK.

## 2026-07-23 — YouTube import: устойчивость + hotfix прод

- **Симптом:** часть импортов «ломается» / job зависает; age-gate и geo-errors.
- **Сейчас на проде:** `YTDLP_PROXY` → `socks5h://`; yt-dlp **2026.7.4**; orphan `running` items сброшены; `sounduk-import` restarted; smoke `eVTXPUF4Oz4` OK.
- **Код:** auto `socks5→socks5h`; больше `player_client`; reclaim stale running; cancel чистит running items; non-retryable для country/age.
- **Остаётся вручную:** `YTDLP_COOKIES_FILE` (Netscape cookies) для age-restricted.

## 2026-07-23 — Wipe cloud library for knyzeviv@gmail.com (Ilya)

- **Причина:** после merge метаданные треков без объектов в S3 → `NoSuchKey` на стриме.
- **Действие:** admin `_cleanup_user_tracks_data` user_id=6 — удалены 264 DB tracks + 398 S3 keys; удалены 9 albums; `library_revision` → 307; upload `database_latest`.
- **Снапшот:** `/var/www/sounduk_backend/backups_local/database_pre_ilya_cloud_wipe_20260723_173935.db`
- **Итог:** tracks=0, albums=0, storage_used=0 для Ilya.

## 2026-07-23 — Merge live SQLite + S3 `database_latest`

- **Проблема:** live `database.db` (12 users / 158 tracks) разошёлся с S3 latest (13 users / 343 tracks). У Ilyи в live были свежие треки (до 2026-07-23), в S3 — другая библиотека + user **Soan**; overlap только 59 треков (knyaz/akmil).
- **Действие:** stop `sounduk` → snapshot live + S3 → `merge_sqlite_dbs.py` (base=live, INSERT missing PK из S3) → swap → upload merged как `database_latest`.
- **Скрипт:** `context/scripts/merge_sqlite_dbs.py`, runner `context/scripts/run_db_merge_prod.sh`.
- **Локальные снапшоты на сервере:** `/var/www/sounduk_backend/backups_local/database_*_20260723_173247.db`; S3 premerge key `backups/database_premerge_20260723_173247.db`.
- **Итог:** users=13, tracks=442, albums=10, Ilya tracks=264 (~1.5 GB metadata), Soan present.
- **Инцидент:** первый старт после merge затёр БД старым S3 из‑за ошибочного «sha differs → restore». Исправлено: если local **новее** S3 по UTC mtime — всегда keep local. Re-apply merged + re-upload latest.
- **db_backup.py:** UTC mtime compare + sha check; не затирает более новый local.

## 2026-07-23 — Albums LWW `updatedAt` (прод)

- **Деплой:** только `api/albums.py` → `178.72.184.68:/var/www/sounduk_backend`, `systemctl restart sounduk`.
- **Поведение:** POST/PUT принимают клиентский `updatedAt`; PUT со старым timestamp не перетирает альбом (soft reject → текущий `AlbumOut`).
- Smoke: `sounduk` active, `/docs` 200. Бэкап: `api/albums.py.bak.*`.

## 2026-07-22 — Hotfix: `cover_data` в PATCH track (прод)

- **Проблема:** клиент слал `cover_data` (base64) в PATCH, на проде поля не было в `TrackUpdateRequest` → Pydantic silently drop → HTTP 200, `cover_path` оставался `None`. Обложки с телефона не доезжали до веба.
- **Деплой (минимальный) на `178.72.184.68`:** `schemas.py` + ветка `cover_data` в `api/tracks.py` (`import base64`). **Не** выкатывали premium-gating YouTube import без полного `auth_utils.py` (сломало бы startup).
- **Клиент:** обложки, выставленные до hotfix, нужно поставить заново.
- **Урок:** после деплоя сверять, что продовыe Pydantic-схемы содержат новые поля request body.

## 2026-07-21 — Audit orphan tracks + daily DB backup

- **Прод API host:** `178.72.184.68` (`emelda`), `/var/www/sounduk_backend` (deploy.sh обновлён).
- **Audit (read-only):** `context/scripts/audit_tracks_s3.py` → 315 tracks, **150 audio_missing** (legacy `uploads/`, нет объекта и в `tracks/`). Отчёт: `context/audit_tracks_s3_2026-07-21.md`. Remediation не делали.
- **db_backup.py:** интервал **24h** (`interval_min=1440`), prune timestamped `backups/database_*.db` старше **90 дней**; `database_latest.db` не удаляется. One-shot prune удалил **1310** старых копий.
- **Деплой:** только `db_backup.py` (+ remote `.backup.*`), `database.db` не трогали вручную. После `systemctl restart sounduk` сработал штатный startup restore из `database_latest.db` (размер 843776, counts: tracks=315 users=14 albums=9) — метаданные на месте.
- Smoke: `sounduk` active, `/docs` 200.

## 2026-06-08 — Миграция API на новый сервер

- **Новый хост:** `138.249.18.60` (`knyzeviv.oblaka.tech`), Ubuntu 24.04, 2 GB RAM + 512 MB swap.
- **Путь:** `/var/www/sounduk_backend`, код + локальные `database.db` и `.env` (июнь 2026).
- **Сервис:** `systemd` unit `sounduk.service` (`uvicorn --workers 1`, `Restart=always`).
- **Nginx:** `/etc/nginx/sites-available/sounduk_backend` — `api.sounduk.ru` и IP → `:8000`.
- **Проверка:** `curl -H "Host: api.sounduk.ru" http://138.249.18.60/` → 200.
- **DNS:** `api.sounduk.ru` → `138.249.18.60` (проверено 2026-06-08).
- **HTTPS:** Let's Encrypt для `api.sounduk.ru`, истекает 2026-09-06.
- **БД:** восстановлена из S3 `backups/database_latest.db` (843 KB, 2026-06-08 15:18 UTC); старый сервер `185.76.242.73` недоступен по SSH.
- **Стриминг:** `STREAM_PRESIGNED_ENABLED=true` — телефон качает с S3 напрямую (VPS не проксирует Selectel boto3).
- **YouTube:** `sounduk-yt-proxy.service` на `138.249.18.60` → SOCKS `127.0.0.1:10801` → `77.110.107.73`; `YTDLP_PROXY=socks5h://127.0.0.1:10801`. Smoke: `eVTXPUF4Oz4` ~5 MB за ~14 с.
- **deploy.sh:** SSH host обновлён на `138.249.18.60`, перезапуск через `systemctl restart sounduk`.

## 2026-06-04 — YouTube import: ConnectError после yt-dlp

- **Причина:** MP3 скачивался через прокси, затем oembed к `youtube.com` без прокси с VPS в РФ → `httpx.ConnectError`.
- **Фикс:** заголовок/duration из yt-dlp (`extract_info`), oembed и RapidAPI/скачивание MP3 обёрнуты в `HTTPException`; при «Повторить» сбрасывается `retry_count`.

## 2026-06-04 — YouTube import: таймаут job ~3 мин

- **Причина:** `socket_timeout=60` в yt-dlp + 3 автоповтора import job — обрыв на медленном прокси; `str(HTTPException)` в БД пустой → в UI только URL.
- **Фикс:** `YTDLP_SOCKET_TIMEOUT=180`, `_format_import_job_error`, fallback RapidAPI при падении yt-dlp, без retry на фатальные ошибки.

## 2026-06-04 — YouTube прокси через 77.110.107.73

- SOCKS5-туннель: systemd `sounduk-yt-proxy.service` на проде → `127.0.0.1:10801` → `root@77.110.107.73`.
- SSH-ключ `/root/.ssh/sounduk_proxy_tunnel` (пароль больше не нужен для туннеля).
- `.env`: `YTDLP_PROXY=socks5h://127.0.0.1:10801`.
- Тест `eVTXPUF4Oz4`: MP3 ~5 MB скачан за ~10 с через прокси; backend `download_youtube_mp3_bytes` — OK.

## 2026-06-04 — YouTube с VPS в РФ: диагностика

- Видео `eVTXPUF4Oz4`: без прокси — bot/SSL ошибки; с прокси — ок.
- В `youtube_converter.py`: `YTDLP_PROXY`, `YTDLP_COOKIES_FILE`, `player_client` android/web.

## 2026-06-04 — YouTube import: yt-dlp вместо RapidAPI

- Локальная конвертация по модели [yt-audio-api](https://github.com/alperensumeroglu/yt-audio-api): `youtube_converter.py`, `yt-dlp` + FFmpeg.
- По умолчанию `YOUTUBE_AUDIO_PROVIDER=ytdlp` (RapidAPI опционален: `rapidapi`).
- На сервере нужны: `apt install ffmpeg`, `pip install yt-dlp`, перезапуск uvicorn.

## 2026-06-04 — YouTube import (RapidAPI youtube-mp310)

- Интеграция с [youtube-mp310](https://rapidapi.com/elisbushaj2/api/youtube-mp310): `GET /download/mp3?url=<youtube_watch_url>`.
- Переменные `.env`: `RAPIDAPI_KEY`, `YOUTUBE_MP3_HOST`, `YOUTUBE_MP3_PATH` (см. `.env.example`).
- `load_dotenv()` в `main.py` и `api/tracks.py` до чтения env.
- Улучшен парсер ответа RapidAPI (plain-text URL и JSON с полем `file` и вложенными ссылками).
- Документация для клиента: `llm_client_app_info.md` §3.1.1.
- На прод добавлены переменные YouTube в `/var/www/sounduk_backend/.env`.

## 2026-06-04 — Деплой backend на прод + SSH

### SSH и доступ

- Сгенерирован ed25519-ключ `~/.ssh/sounduk_cursor` (комментарий `cursor-sounduk-deploy`).
- Публичный ключ добавлен в `root@185.76.242.73:~/.ssh/authorized_keys`.
- Проверен вход по ключу (`BatchMode=yes`, без пароля).
- Добавлен алиас в `~/.ssh/config`: хост `sounduk-prod` → `185.76.242.73`, user `root`, `IdentityFile ~/.ssh/sounduk_cursor`.
- Установлен `sshpass` (Homebrew) для одноразовой первичной настройки ключа; дальше деплой только по ключу.

### Инфраструктура на сервере (фактическая)

- **SoundUK API:** `/var/www/sounduk_backend`
  - Процесс: `/var/www/sounduk_backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4`
  - **Нет** unit `sounduk.service` (systemd) — перезапуск вручную через `nohup` / `pkill`.
  - **Нет** копии в `/home/root/sounduk_backend` (только шаблон в `DEPLOY.md`).
- **Nginx:** `/etc/nginx/sites-enabled/sounduk_backend`
  - `api.sounduk.ru` → `proxy_pass http://127.0.0.1:8000` (основной API)
  - `/driver-api/` → `http://127.0.0.1:8010/` (отдельный сервис, не SoundUK)
- **Другой сервис на том же хосте:** `/opt/driver_test_backend` (uvicorn `:8010`) — не удалялся.
- **Сайт panop:** `/var/www/panop.sounduk.ru` — оставлен; удалён только бэкап `panop.sounduk.ru_backup_`.

### Очистка перед деплоем

**Локально** (`mega_sounduk/sounduk_backend`):

- Удалены `__pycache__/`, `.pytest_cache/`, `server.err`, `server.log`, `._*`, `.pyc` вне `venv/`.

**На сервере:**

- Удалены `panop.sounduk.ru_backup_`, `sites-enabled/sounduk_backend.bak.20260407174418`.
- Удалены macOS-файлы `._*` в `/var/www/sounduk_backend`.
- Удалены `*.backup.*` (если были) в корне backend до 4 уровней.

### Деплой

- `rsync` локальный `sounduk_backend/` → `root@185.76.242.73:/var/www/sounduk_backend/`
  - Исключены: `venv/`, `.env`, `.git/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, `._*`, `server.log`, `server.err`
  - **Замечание:** в этот прогон попали `database.db` и `uploads/` — после выката S3-синхронизация сообщила «локальная БД актуальна»; для следующих деплоев нужно явно исключать `database.db` и `uploads/`.
- На сервере: `python migrate_albums.py` — все миграции уже применены (`cover_art`, PK, audit log и др.).
- Перезапуск uvicorn (после `pkill` API кратко отдавал 502, затем поднят снова).
- Проверка: `http://127.0.0.1:8000/docs` и `https://api.sounduk.ru/docs` → **200**.

### Обновления в репозитории

- `context/scripts/deploy.sh`: пароль убран, деплой через `~/.ssh/sounduk_cursor`, `LOCAL_PATH` → монорепо `mega_sounduk/sounduk_backend`, точный `pkill` по пути venv, URL прод → `https://api.sounduk.ru`.

### Риски / follow-up

- Пароль root ранее был в `deploy.sh` и `ssh_info.md` — рекомендуется ротация и вычищение из git.
- Нет systemd — при `pkill` возможен простой API; желательно `sounduk.service`.
- Следующий деплой: rsync с `--exclude database.db --exclude uploads/`.

## 2026-04-30 02:40 (UTC-7)

- Настроен SSH-доступ для Cursor через ключ `~/.ssh/sounduk_cursor`.
- Проверено подключение к серверу `185.76.242.73`: вход успешен (`root`), команда в удаленной сессии выполнена.
- Проведена диагностика SSH для проблемы входа из админ-панели: `sshd` и `ufw` работают штатно, password/root login разрешены, блокировок fail2ban по текущим IP нет.
- В логах `journalctl -u ssh` найдены попытки клиентов с устаревшим key exchange (`diffie-hellman-group1-sha1`) и невалидным протоколом (`GET / HTTP/1.1`), что может объяснять сбой некоторых панелей.

## 2026-04-30 02:15 (UTC-7)

- Выполнен `/explore-context-init` для `sounduk_backend`.
- Проверен существующий контекст в `context/` без перезаписи текущих документов.
- Добавлены недостающие файлы: `INDEX.md`, `00_overview.md`, `01_architecture.md`, `02_risks_and_debt.md`, `change_log.md`.
- Подготовлены базовые правила инициализации Cursor в `.cursorrules` и `.cursorignore`.
