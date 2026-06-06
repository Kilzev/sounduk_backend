# Документация для разработки Клиентского Приложения (Flutter)

Этот документ содержит информацию, необходимую для разработки пользовательского приложения Sounduk.

## 1. Базовая информация

*   **Base URL (Production):** `https://api.sounduk.ru` (только HTTPS — HSTS включён на 2 года)
*   **Base URL (Dev):** `http://10.0.2.2:8000` (Android эмулятор) или `http://127.0.0.1:8000` (iOS / Web).
*   **Content-Type:** `application/json` (кроме загрузки файлов).

**Важно:** В production все запросы должны идти по HTTPS. Любое обращение по HTTP автоматически редиректится на HTTPS.

## 2. Аутентификация

JWT (Bearer Token). **Логин по email** — username используется только как отображаемое имя аккаунта.

### 2.1 Регистрация
**POST** `/api/auth/register`

**Request Body:**
```json
{
  "username": "Вася Пупкин",
  "email": "user@example.com",
  "password": "strongpassword"
}
```

*   `username` — отображаемое имя (уникальное, но используется только для UI)
*   `email` — основной идентификатор для входа (уникальный)
*   `password` — пароль

**Response (201 Created):**
```json
{
  "id": 1,
  "username": "Вася Пупкин",
  "email": "user@example.com",
  "created_at": "2026-04-05T10:00:00",
  "storage_limit": 1073741824,
  "is_premium": false,
  "is_verified": false
}
```

После регистрации на email отправляется 6-значный код подтверждения. Без подтверждения нельзя загружать треки и покупать премиум.

**Ошибки:**
*   `400`: "Пользователь с таким именем уже существует"
*   `400`: "Этот email уже зарегистрирован"
*   `429`: "Слишком много регистраций с этого IP. Попробуйте позже." (макс. 3 за 24 часа)

### 2.2 Подтверждение email
**POST** `/api/auth/verify`

```json
{
  "email": "user@example.com",
  "code": "624768"
}
```

**Response (200 OK):** `{"message": "Email подтверждён"}`

**Ошибки:**
*   `400`: "Неверный код"
*   `400`: "Код истёк. Запросите новый." (код живёт 10 минут)

### 2.3 Повторная отправка кода подтверждения
**POST** `/api/auth/resend-code`

```json
{
  "email": "user@example.com"
}
```

**Response:** `{"message": "Код отправлен повторно"}`

**Ошибки:**
*   `429`: "Подождите N сек. перед повторной отправкой" (cooldown 60 сек)

### 2.4 Логин
**POST** `/api/auth/login`

```json
{
  "email": "user@example.com",
  "password": "strongpassword"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Важно:** Сохраните `access_token` в SecureStorage и передавайте через заголовок `Authorization: Bearer <token>`.

**Ошибки:**
*   `401`: "Неверный email или пароль"
*   `429`: "Слишком много попыток входа с этого IP. Попробуйте позже." (3 попытки — 45 сек, 5 — 10 мин, 7 — 30 дней)

### 2.5 Забыли пароль
**POST** `/api/auth/forgot-password`

Запрашивает код сброса пароля на email.

```json
{
  "email": "user@example.com"
}
```

**Response (200 OK):** `{"message": "Если такой email существует, код отправлен"}`

**Примечание:** Ответ одинаковый даже если email не зарегистрирован (защита от перебора email'ов).

**Ошибки:**
*   `429`: "Подождите N сек. перед повторным запросом" (cooldown 60 сек)

### 2.6 Сброс пароля
**POST** `/api/auth/reset-password`

Сбрасывает пароль по коду из письма.

```json
{
  "email": "user@example.com",
  "code": "624768",
  "new_password": "newstrongpassword"
}
```

**Response (200 OK):** `{"message": "Пароль успешно сброшен"}`

**Важно:** После успешного сброса email автоматически считается подтверждённым.

**Ошибки:**
*   `400`: "Неверный код или email"
*   `400`: "Код истёк. Запросите новый."
*   `429`: "Слишком много попыток сброса. Попробуйте позже."

### 2.7 Получение профиля
**GET** `/api/auth/me`

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "Вася Пупкин",
  "email": "user@example.com",
  "created_at": "2026-04-05T10:00:00",
  "storage_limit": 1073741824,
  "storage_used": 52428800,
  "is_premium": false,
  "is_verified": true
}
```

## 3. Треки

**Важно:** Все операции с треками требуют подтверждённый email (`is_verified: true`). Без подтверждения — `403 Forbidden`: "Подтвердите email для доступа к этой функции".

### 3.1 Загрузка трека
**POST** `/api/tracks/upload`

**Header:** `Content-Type: multipart/form-data`

**Body (Form Data):**
*   `file`: Файл (mp3, m4a, wav, flac)
*   `title`: String
*   `artist`: String
*   `album`: String (опционально)
*   `duration`: Int (в секундах)
*   `created_at`: String ISO datetime (опционально)

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Song Title",
  "artist": "Artist Name",
  "album": "Album Name",
  "duration": 180,
  "file_size": 5242880,
  "created_at": "2026-04-05T10:00:00",
  "is_frozen": false
}
```

**Ошибки:**
*   `400`: "Неподдерживаемый формат файла"
*   `403`: "Превышен лимит хранилища" / "Недостаточно места"
*   `403`: "Подтвердите email для доступа к этой функции"
*   `403`: "Аккаунт ограничен"

### 3.1.1 Импорт с YouTube (yt-dlp + FFmpeg)

Backend конвертирует ссылку YouTube в MP3 **на сервере** (без RapidAPI): `yt-dlp` + `FFmpeg`, как в [yt-audio-api](https://github.com/alperensumeroglu/yt-audio-api). На сервере должны быть установлены `ffmpeg` и пакет `yt-dlp`. Env: `YOUTUBE_AUDIO_PROVIDER=ytdlp` (по умолчанию).

**Один трек** — `POST` `/api/tracks/import/youtube/track`

```json
{
  "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "album_id": "optional-album-id"
}
```

**Плейлист (синхронно, до 100 видео)** — `POST` `/api/tracks/import/youtube/playlist`  
Тело такое же. Для длинных плейлистов лучше jobs (ниже).

**Плейлист (фон, 202 Accepted)** — `POST` `/api/tracks/import/youtube/jobs`

```json
{
  "youtube_url": "https://www.youtube.com/playlist?list=PLAYLIST_ID",
  "album_id": "optional-album-id",
  "client_request_id": "optional-idempotency-key"
}
```

Ответ: `{ "job_id": "...", "status": "pending" }`. Статус job — существующие эндпоинты import jobs.

**Поддерживаемые URL:** `youtube.com/watch?v=`, `youtu.be/`, плейлист `?list=`.  
**Ошибки:** `400` некорректный URL; `502` ошибка yt-dlp/FFmpeg или сеть; `403` лимит хранилища.

Опционально `YOUTUBE_AUDIO_PROVIDER=rapidapi` + `RAPIDAPI_KEY` (если RapidAPI доступен с сервера).

### 3.2 Список треков
**GET** `/api/tracks`

```json
{
  "tracks": [
    {
      "id": "uuid",
      "title": "Title",
      "artist": "Artist",
      "album": null,
      "duration": 180,
      "file_size": 1048576,
      "created_at": "2026-04-05T10:00:00",
      "is_frozen": false
    }
  ],
  "total": 1
}
```

**О заморозке:** Треки, превышающие текущий лимит, помечаются `is_frozen: true`. Их нельзя слушать — нужно оплатить тариф или удалить старые.

### 3.3 Обложка трека
**GET** `/api/tracks/{track_id}/cover`

Возвращает JPEG-изображение обложки.

### 3.4 Стриминг
**GET** `/api/tracks/{track_id}/stream`

Возвращает аудио-поток с поддержкой Range requests.

**Для плееров без заголовков:**
1. **GET** `/api/tracks/{track_id}/token` → `{"token": "...", "url": "/api/tracks/play/..."}`
2. **GET** `/api/tracks/play/{token}` — воспроизведение без Authorization header.

### 3.5 Удаление трека
**DELETE** `/api/tracks/{track_id}` → `204 No Content`

## 4. Альбомы

**Важно:** API альбомов — **per-album CRUD**, не full-replace. Каждое действие работает с одним альбомом.

### Общие правила
- `id` генерирует **клиент** в формате `<millis>-<6 hex random>`, например `1712345678901-a3f21c`. Сервер не переназначает.
- Доступ к чужому альбому → `404 Not Found` (не 403, чтобы не раскрывать факт существования).
- `title` — обязательное, непустое, до 200 символов.
- `description` — опционально, до 2000 символов.
- `trackIds` — массив строк, **сервер не валидирует существование трек-ID** (клиент может хранить local-only треки, которых нет на сервере).
- `coverArt` — **base64-строка** изображения (PNG/JPEG) или `null`. Лимит 2 MB raw.
- `createdAt`, `updatedAt` — ISO 8601, ставит **сервер**. Клиент может передавать как hint, но финальное значение — серверное.
- Поле `isLocal` — **игнорируется** сервером (клиентское).

### 4.1 Получение всех альбомов
**GET** `/api/albums`

Используется при pull-to-refresh, переключении вкладок, возврате из фона.

**Response (200):**
```json
[
  {
    "id": "1712345678901-a3f21c",
    "title": "Любимые",
    "description": null,
    "trackIds": ["track_id_1", "track_id_2"],
    "coverArt": null,
    "createdAt": "2026-04-01T12:00:00.000000",
    "updatedAt": "2026-04-05T09:30:00.000000"
  }
]
```

Пустой список → `[]`, не 404.

### 4.2 Создание альбома
**POST** `/api/albums`

**Request Body:**
```json
{
  "id": "1712345678901-a3f21c",
  "title": "Новый альбом",
  "description": "Опционально",
  "trackIds": [],
  "coverArt": null
}
```

**Response (201):** созданный объект альбома (см. формат из 4.1).

**Ошибки:**
- `400`: невалидные поля (пустой title, плохой base64 в coverArt, размер обложки > 2 MB)
- `409`: альбом с таким `id` уже существует у пользователя
- `422`: нарушение Pydantic-валидации (отсутствует обязательное поле)

### 4.3 Обновление альбома (partial update)
**PUT** `/api/albums/{id}`

Все поля опциональны — сервер обновит только переданные. Остальные остаются как были.

**Request Body:**
```json
{
  "title": "Новое название",
  "description": "Новое описание",
  "trackIds": ["t1", "t2", "t3"],
  "coverArt": "iVBORw0KGgoAAAANS..."
}
```

**Очистка обложки:** передать `"coverArt": ""` (пустая строка) — сервер уберёт обложку.

**Response (200):** обновлённый объект альбома.

**Ошибки:**
- `404`: альбом не существует или принадлежит другому пользователю
- `400`: невалидные поля

### 4.4 Удаление альбома
**DELETE** `/api/albums/{id}`

**Response:** `204 No Content`

**Ошибки:**
- `404`: уже удалён или не существует (клиент может интерпретировать как успех ради идемпотентности)

### Когда что вызывать

| Событие в UI | Эндпоинт |
|--------------|----------|
| Открытие экрана альбомов, pull-to-refresh | `GET /api/albums` |
| Создание нового облачного альбома | `POST /api/albums` |
| Переименование, изменение описания | `PUT /api/albums/{id}` |
| Добавление/удаление треков из альбома | `PUT /api/albums/{id}` с `trackIds` |
| Замена обложки | `PUT /api/albums/{id}` с `coverArt` |
| Удаление альбома из облака | `DELETE /api/albums/{id}` |
| Local-only альбом (mobile offline) | Не вызывать серверные эндпоинты |

## 5. Хранилище

### 5.1 Подробное использование
**GET** `/api/users/storage/usage`

```json
{
  "storage_limit": 1073741824,
  "storage_used": 52428800,
  "percentage": 4.88
}
```

### 5.2 Статистика
**GET** `/api/users/storage`

```json
{
  "used_space": 52428800,
  "storage_limit": 1073741824,
  "used_percentage": 4.88
}
```

## 6. Платежи (YooKassa)

**Важно:** Создание платежа требует подтверждённый email.

### Тарифные планы

| ID | Описание | Цена | Лимит | Срок |
|----|----------|------|-------|------|
| `storage_pack_3gb` | Тариф 3 ГБ | 65 руб | 3 ГБ | 30 дней |
| `storage_pack_5gb` | Тариф 5 ГБ | 99 руб | 5 ГБ | 30 дней |
| `storage_pack_20gb` | Тариф 20 ГБ | 220 руб | 20 ГБ | 30 дней |

По умолчанию **1 ГБ бесплатно**. Покупка тарифа **устанавливает** лимит (не суммирует). Повторная покупка продлевает срок.

### 6.1 Создание платежа
**POST** `/api/payments/create`

```json
{"product_id": "storage_pack_3gb"}
```

**Response:**
```json
{
  "payment_id": "2d3f4a5b-...",
  "confirmation_url": "https://yoomoney.ru/checkout/..."
}
```

Откройте `confirmation_url` в WebView/браузере → оплата → опрашивайте статус.

### 6.2 Проверка статуса
**GET** `/api/payments/{payment_id}/status`

```json
{"status": "succeeded"}
```

Статусы: `pending`, `waiting_for_capture`, `succeeded`, `canceled`. При `succeeded` премиум активируется автоматически.

## 7. Управление аккаунтом

### 7.1 Обновление профиля
**PATCH** `/api/users/me`

```json
{
  "username": "New Name",
  "password": "new_password"
}
```
Оба поля опциональны.

### 7.2 Удаление аккаунта
**DELETE** `/api/users/me` → `204 No Content`

## 8. UX-флоу

### Регистрация
```
1. Экран регистрации: username + email + password → POST /register
2. Экран ввода кода: 6-значный код с email → POST /verify
   - Кнопка "Отправить повторно" (60 сек cooldown) → POST /resend-code
3. Перейти на главный экран
```

### Забыли пароль
```
1. Экран "Забыли пароль": email → POST /forgot-password
2. Экран ввода кода: 6-значный код с email + новый пароль → POST /reset-password
3. После успеха — автоматический логин с новым паролем
```

## 9. Обработка ошибок

| Код | Значение | Действие в UI |
|-----|----------|---------------|
| `400` | Невалидные данные | Показать detail пользователю |
| `401` | Токен невалиден | Перейти на экран логина |
| `403` + "Аккаунт ограничен" | Пользователь забанен | Разлогинить, показать сообщение |
| `403` + "Подтвердите email" | Email не подтверждён | Перенаправить на экран верификации |
| `403` + "заморожен" | Трек за пределами лимита | Предложить оплатить или удалить треки |
| `429` | Rate limit | Показать "Попробуйте позже" с таймером |
