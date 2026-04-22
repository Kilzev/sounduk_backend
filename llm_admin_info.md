# Документация для разработки Admin Panel (Flutter)

Этот документ содержит информацию для разработки админ-панели проекта Sounduk. Бэкенд — **FastAPI**.

## 1. Базовая информация

*   **Base URL (Production):** `https://api.sounduk.ru` (только HTTPS — HSTS включён на 2 года)
*   **Base URL (Dev):** `http://10.0.2.2:8000` (Android эмулятор) или `http://127.0.0.1:8000` (iOS / Web)
*   **Content-Type:** `application/json`

**Важно:** В production все запросы должны идти по HTTPS. Обращение по HTTP автоматически редиректится на HTTPS.

## 2. Аутентификация

Для доступа к админским эндпоинтам необходим **JWT токен** пользователя с `is_admin = true`.

### Логин
**POST** `/api/auth/login`

```json
{
  "email": "admin@example.com",
  "password": "secret_password"
}
```

Логин происходит по **email**, не по username.

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

Все запросы: `Authorization: Bearer <access_token>`

**Создание первого админа** — через скрипт `create_admin_user.py` на сервере или вручную:
```sql
UPDATE users SET is_admin = 1 WHERE email = 'admin@example.com';
```

После первого админа — новых можно назначать через `PATCH /api/admin/users/{user_id}` с полем `is_admin: true`.

## 3. Эндпоинты Admin Panel

Все эндпоинты в группе `/api/admin`. Требуют токен администратора, иначе — `403 Forbidden`.

### 3.1 Список пользователей
**GET** `/api/admin/users`

**Query Parameters:**
*   `skip` (int, default=0) — смещение
*   `limit` (int, default=100) — количество

**Response:**
```json
[
  {
    "id": 1,
    "username": "user1",
    "email": "user1@example.com",
    "created_at": "2024-01-15T10:00:00",
    "is_admin": false,
    "is_premium": false,
    "is_verified": true,
    "storage_limit": 1073741824,
    "is_restricted": false,
    "storage_used": 102400
  }
]
```

### 3.2 Детали пользователя
**GET** `/api/admin/users/{user_id}`

**Response:** один объект `AdminUserResponse` (как выше).

### 3.3 Редактирование пользователя
**PATCH** `/api/admin/users/{user_id}`

Все поля опциональны — отправляйте только то, что нужно изменить.

**Request Body:**
```json
{
  "username": "new_display_name",
  "email": "new@email.com",
  "password": "new_password",
  "is_premium": true,
  "storage_limit": 3221225472,
  "is_restricted": true,
  "is_verified": true,
  "is_admin": false
}
```

**Описание полей:**

| Поле | Тип | Описание |
|------|-----|----------|
| `username` | string | Отображаемое имя (проверяется уникальность) |
| `email` | string | Новый email (проверяется уникальность, используется для логина) |
| `password` | string | Сброс пароля (хешируется автоматически) |
| `is_premium` | bool | Премиум-статус |
| `storage_limit` | int | Лимит хранилища в байтах |
| `is_restricted` | bool | Блокировка аккаунта |
| `is_verified` | bool | Статус верификации email (админ может подтвердить вручную) |
| `is_admin` | bool | Назначение/снятие прав админа |

**Response:** обновлённый объект `AdminUserResponse`.

**Ошибки:**
*   `400`: "Username already taken"
*   `400`: "Email already registered"
*   `403`: "Нельзя снять с себя права администратора"
*   `403`: "Нельзя заблокировать самого себя"
*   `403`: "В системе должен остаться хотя бы один активный администратор"

### 3.4 Удаление пользователя
**DELETE** `/api/admin/users/{user_id}`

Удаляет пользователя **и все его файлы** с диска.

**Response:** `204 No Content`

**Защиты:**
*   `403`: "Нельзя удалить самого себя"
*   `403`: "Нельзя удалить последнего администратора"

### 3.5 Журнал действий администраторов (Audit Log)
**GET** `/api/admin/audit-log`

Возвращает журнал всех мутирующих действий администраторов (изменения, удаления). Сортировка — от новых к старым.

**Query Parameters:**
*   `skip` (int, default=0) — смещение
*   `limit` (int, default=100) — количество
*   `target_user_id` (int, optional) — фильтр по ID пользователя, к которому применялось действие

**Response:**
```json
[
  {
    "id": 42,
    "admin_id": 1,
    "admin_username": "admin",
    "action": "update_user",
    "target_user_id": 5,
    "details": "{\"is_premium\": {\"old\": false, \"new\": true}}",
    "ip_address": "185.76.242.73",
    "created_at": "2026-04-05T14:30:00"
  }
]
```

**Типы действий (`action`):**
*   `update_user` — обычные изменения полей
*   `grant_admin` — назначение админом (is_admin: false → true)
*   `revoke_admin` — снятие админских прав
*   `delete_user` — удаление пользователя

**Поле `details`** — JSON-строка с diff изменений (старое/новое значение).

### 3.6 Треки пользователя
**GET** `/api/admin/users/{user_id}/tracks`

**Response:**
```json
{
  "tracks": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Song Title",
      "artist": "Artist Name",
      "album": "Album Name",
      "duration": 180,
      "file_size": 1024000,
      "created_at": "2024-01-15T10:00:00",
      "is_frozen": false
    }
  ],
  "total": 1
}
```

## 4. Стриминг треков (для прослушивания в админке)

Администратор может слушать треки любого пользователя. Проверка `user_id` отключена для админов.

**GET** `/api/tracks/{track_id}/stream?token=<admin_token>`

*   Токен передаётся через query-параметр (для совместимости с аудиоплеерами, которые не поддерживают заголовки).
*   URL можно вставлять напрямую в Flutter-аудиоплеер.
*   Поддерживает Range requests (перемотка).

### Обложка трека
**GET** `/api/tracks/{track_id}/cover`

Возвращает JPEG. Требует токен через заголовок `Authorization`.

## 5. Типы данных (Dart Models)

**AdminUserResponse:**
```dart
class AdminUser {
  final int id;
  final String username;
  final String email;
  final DateTime createdAt;
  final bool isAdmin;
  final bool isPremium;
  final bool isVerified;
  final int storageLimit;    // bytes
  final bool isRestricted;
  final int storageUsed;     // bytes
}
```

**Track:**
```dart
class Track {
  final String id;           // UUID
  final String title;
  final String artist;
  final String? album;
  final int duration;        // seconds
  final int fileSize;        // bytes
  final DateTime createdAt;
  final bool isFrozen;
}
```

**AdminAuditLog:**
```dart
class AdminAuditLog {
  final int id;
  final int adminId;
  final String adminUsername;
  final String action;          // update_user, grant_admin, revoke_admin, delete_user
  final int? targetUserId;
  final String? details;        // JSON-строка с diff
  final String? ipAddress;
  final DateTime createdAt;
}
```

## 6. UI-рекомендации для админки

### Список пользователей
*   Показывать: username, email, `is_verified` (иконка), `is_premium` (бейдж), storage used/limit (прогресс-бар)
*   Цветовая индикация: забаненные (`is_restricted`) — красным, неверифицированные — серым
*   Фильтры: все / премиум / забаненные / неверифицированные

### Детали пользователя
*   Информация об аккаунте + список треков
*   Кнопки: заблокировать, подтвердить email вручную, изменить лимит, удалить, назначить/снять админа
*   Мини-плеер для прослушивания треков
*   Кнопки над самим собой (текущий админ) должны быть задизейблены для опасных действий — сервер всё равно вернёт 403

### Audit Log (журнал действий)
*   Отдельный экран со списком действий всех админов
*   Фильтр по `target_user_id` — посмотреть историю изменений конкретного пользователя
*   Парсить `details` как JSON для красивого отображения diff'ов (старое → новое значение)
*   Показывать `admin_username`, `action`, `ip_address`, `created_at`
*   Цветовая кодировка по `action`: `grant_admin` — зелёный, `revoke_admin`/`delete_user` — красный, `update_user` — серый

### Полезные вычисления
```dart
// Процент использования хранилища
double usagePercent = (storageUsed / storageLimit) * 100;

// Форматирование байт
String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1048576) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  if (bytes < 1073741824) return '${(bytes / 1048576).toStringAsFixed(1)} MB';
  return '${(bytes / 1073741824).toStringAsFixed(2)} GB';
}
```

## 7. Важные нюансы

1.  **Логин по email:** Пользователи входят по email + password. Username — только отображаемое имя.
2.  **Email-верификация:** Админ может вручную верифицировать пользователя через `PATCH` с `"is_verified": true` — полезно для служебных аккаунтов.
3.  **Блокировка:** При `is_restricted: true` пользователь получает `403` на все запросы с токеном. Разблокировка — `PATCH` с `"is_restricted": false`.
4.  **Пароли:** В БД хранятся только хеши (Argon2). Админ не видит пароли, но может сбросить через `"password": "new_pass"`.
5.  **Сброс пароля пользователем:** Через `/api/auth/forgot-password` + `/api/auth/reset-password` — код приходит на email.
6.  **Удаление:** Каскадное — удаляются все треки, платежи, альбомы и файлы на диске.
7.  **Rate limits:** Не применяются к админским эндпоинтам.

## 8. Защита от ошибок админа

Сервер автоматически защищает систему от опасных действий:

| Действие | Защита |
|----------|--------|
| Снять с себя права админа | `403` — "Нельзя снять с себя права администратора" |
| Заблокировать самого себя | `403` — "Нельзя заблокировать самого себя" |
| Удалить самого себя | `403` — "Нельзя удалить самого себя" |
| Снять/удалить/заблокировать **последнего** активного админа | `403` — "В системе должен остаться хотя бы один активный администратор" |

Также **все мутирующие действия** (PATCH/DELETE) автоматически записываются в `admin_audit_log` с указанием админа, IP-адреса и diff'а изменений.
