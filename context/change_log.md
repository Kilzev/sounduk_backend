# Change Log

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
