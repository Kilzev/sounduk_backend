# Документация для разработки Admin Panel (Flutter)

Этот документ содержит информацию, необходимую для разработки клиентской части админ-панели для проекта Sounduk. Бэкенд реализован на **FastAPI**.

## 1. Базовая информация

*   **Base URL (Localhost):** `http://127.0.0.1:8000`
*   **Base URL (Android Emulator):** `http://10.0.2.2:8000`
*   **Content-Type:** `application/json`

## 2. Аутентификация

Для доступа к админским эндпоинтам необходим **JWT токен**.
Пользователь должен иметь флаг `is_admin = true` в базе данных.

### Получение токена (Логин)
**POST** `/api/auth/login`

**Request Body:**
```json
{
  "username": "admin_user",
  "password": "secret_password"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Все последующие запросы к защищённым маршрутам должны содержать заголовок:
`Authorization: Bearer <access_token>`

## 3. Эндпоинты Админ-панели

Все эндпоинты находятся в группе `/api/admin`.

### 3.1. Получение списка всех пользователей
**GET** `/api/admin/users`

**Query Parameters:**
*   `skip` (int, default=0): Смещение для пагинации.
*   `limit` (int, default=100): Количество пользователей.

**Response (List[AdminUserResponse]):**
```json
[
  {
    "id": 1,
    "username": "user1",
    # "email": "user1@example.com", // Удалено
    "created_at": "2023-10-27T10:00:00",
    "is_admin": false,
    "is_premium": false,
    "storage_limit": 1073741824,
    "is_restricted": false,
    "storage_used": 102400
  },
  ...
]
```

### 3.2. Получение детальной информации о пользователе
**GET** `/api/admin/users/{user_id}`

**Response (AdminUserResponse):**
То же самое, что и один элемент списка выше.

### 3.3. Редактирование пользователя
**PATCH** `/api/admin/users/{user_id}`

Позволяет изменить любые поля пользователя. Все поля в body опциональны (отправляйте только то, что нужно изменить).

**Request Body (UserUpdateAdmin):**
```json
{
  "username": "new_username",          // Опционально
  // "email": "new@email.com",            // Удалено
  "password": "new_password",          // Опционально (сброс пароля)
  "is_premium": true,                  // Опционально
  "storage_limit": 2147483648,         // Опционально (в байтах, например 2GB)
  "is_restricted": true                // Опционально (блокировка/ограничение)
}
```

**Response (AdminUserResponse):**
Обновленный объект пользователя.

### 3.4. Удаление пользователя
**DELETE** `/api/admin/users/{user_id}`

Удаляет пользователя **и все его загруженные файлы** с диска.

**Response:** `204 No Content`

### 3.5. Просмотр треков пользователя
**GET** `/api/admin/users/{user_id}/tracks`

**Response (TracksList):**
```json
{
  "tracks": [
    {
      "id": "uuid-string",
      "title": "Song Title",
      "artist": "Artist Name",
      "album": "Album Name",
      "duration": 180,
      "file_size": 1024000,
      "created_at": "2023-10-27T10:00:00"
    }
  ],
  "total": 1
}
```

## 4. Работа с файлами (Стриминг)

Администратор имеет право прослушивать треки любого пользователя.
Для этого используется стандартный эндпоинт стриминга, но **токен администратора должен быть передан через query-параметр**, так как стандартные HTML `<audio>` теги и многие плееры не поддерживают передачу заголовков авторизации.

**GET** `/api/tracks/{track_id}/stream?token=<admin_token>`

*   **Header `Authorization`:** Не обязателен, если передан параметр `token`.
*   **Query Param `token`:** JWT токен администратора.

Бэкенд автоматически распознает администратора и разрешит доступ к файлу, даже если он принадлежит другому пользователю (проверка `user_id` отключается для админов).

Этот URL можно напрямую вставлять в аудиоплеер Flutter.

## 5. Типы данных (Dart Models Hint)

При генерации моделей для Flutter ориентируйтесь на следующие типы:

**User:**
*   `id`: `int`
*   `username`: `String`
*   `is_premium`: `bool`
*   `storage_limit`: `int` (bytes)
*   `is_restricted`: `bool`
*   `storage_used`: `int` (bytes)

**Track:**
*   `id`: `String` (UUID)
*   `title`: `String`
*   `artist`: `String`
*   `duration`: `int` (seconds)
*   `file_size`: `int` (bytes)

## 6. Важные нюансы

1.  **Создание админа:** API для создания администраторов отсутствует. Первый админ должен быть назначен вручную через доступ к БД:
    `UPDATE users SET is_admin = 1 WHERE username = 'my_admin_login';`
2.  **Ошибки:** Стандартные коды HTTP (401 - Unauthorized, 403 - Forbidden, 404 - Not Found).
3.  **Валидация:** При изменении `username` бэкенд проверяет уникальность и вернет 400, если занято.
