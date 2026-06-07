# migrate_albums.py - Миграции БД
# 1. Композитный PK для таблицы albums (id + user_id)
# 2. Удаление колонки plain_password из таблицы users
# 3. Добавление email-верификации и антифрод полей
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")


def migrate_add_album_cover_art(cursor):
    """Добавляет cover_art, если таблица создана без этой колонки."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='albums'")
    if not cursor.fetchone():
        print("[albums] Таблица не существует — пропуск cover_art")
        return

    cursor.execute("PRAGMA table_info(albums)")
    column_names = [col[1] for col in cursor.fetchall()]
    if "cover_art" in column_names:
        print("[albums] Колонка cover_art уже есть — пропуск")
        return

    print("[albums] Добавление колонки cover_art...")
    cursor.execute("ALTER TABLE albums ADD COLUMN cover_art BLOB")
    print("[albums] cover_art добавлена")


def migrate_add_album_cover_path(cursor):
    """Добавляет cover_path (S3 key) для обложек альбомов."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='albums'")
    if not cursor.fetchone():
        print("[albums] Таблица не существует — пропуск cover_path")
        return

    cursor.execute("PRAGMA table_info(albums)")
    column_names = [col[1] for col in cursor.fetchall()]
    if "cover_path" in column_names:
        print("[albums] Колонка cover_path уже есть — пропуск")
        return

    print("[albums] Добавление колонки cover_path...")
    cursor.execute("ALTER TABLE albums ADD COLUMN cover_path TEXT")
    print("[albums] cover_path добавлена")


def migrate_albums(cursor):
    """Миграция albums: PK (id) -> PK (id, user_id)"""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='albums'")
    if not cursor.fetchone():
        print("[albums] Таблица не существует — пропуск")
        return

    cursor.execute("PRAGMA table_info(albums)")
    columns = cursor.fetchall()
    pk_columns = [col[1] for col in columns if col[5] > 0]

    if len(pk_columns) > 1:
        print("[albums] Композитный PK уже установлен — пропуск")
        return

    print("[albums] Миграция PK (id) -> PK (id, user_id)...")

    cursor.executescript("""
        ALTER TABLE albums RENAME TO albums_old;

        CREATE TABLE albums (
            id VARCHAR NOT NULL,
            user_id INTEGER NOT NULL,
            title VARCHAR NOT NULL,
            description TEXT,
            cover_art BLOB,
            track_ids JSON DEFAULT '[]',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id, user_id),
            FOREIGN KEY(user_id) REFERENCES users (id)
        );

        INSERT INTO albums (id, user_id, title, description, cover_art, track_ids, created_at, updated_at)
        SELECT id, user_id, title, description, cover_art, track_ids, created_at, updated_at
        FROM albums_old;

        DROP TABLE albums_old;
    """)

    count = cursor.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
    print(f"[albums] Готово. Записей: {count}")


def migrate_remove_plain_password(cursor):
    """Удаление колонки plain_password из таблицы users"""
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "plain_password" not in column_names:
        print("[users] Колонка plain_password уже удалена — пропуск")
        return

    print("[users] Удаление колонки plain_password (открытые пароли)...")

    keep_columns = [col[1] for col in columns if col[1] != "plain_password"]
    cols_str = ", ".join(keep_columns)

    cursor.executescript(f"""
        ALTER TABLE users RENAME TO users_old;

        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            username VARCHAR NOT NULL UNIQUE,
            hashed_password VARCHAR NOT NULL,
            created_at DATETIME,
            is_admin BOOLEAN DEFAULT 0,
            is_premium BOOLEAN DEFAULT 0,
            premium_expires_at DATETIME,
            storage_limit BIGINT DEFAULT 1073741824,
            is_restricted BOOLEAN DEFAULT 0,
            recovery_code_enc VARCHAR
        );

        INSERT INTO users ({cols_str})
        SELECT {cols_str}
        FROM users_old;

        DROP TABLE users_old;
    """)

    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"[users] Готово. Пользователей: {count}, plain_password удалён")


def migrate_add_email_verification(cursor):
    """Добавление полей email-верификации в таблицу users"""
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "email" in column_names and "is_verified" in column_names:
        print("[users] Поля email-верификации уже существуют — пропуск")
        return

    print("[users] Добавление полей email-верификации...")

    if "email" not in column_names:
        # Существующим пользователям ставим email = username@legacy.local (заглушка)
        cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR DEFAULT ''")
        # Заполняем email для существующих пользователей
        cursor.execute("UPDATE users SET email = username || '@legacy.local' WHERE email = ''")
        print("[users] Колонка email добавлена (существующие пользователи получили заглушку)")

    if "is_verified" not in column_names:
        # Существующие пользователи считаются верифицированными
        cursor.execute("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0")
        cursor.execute("UPDATE users SET is_verified = 1")
        print("[users] Колонка is_verified добавлена (существующие пользователи верифицированы)")

    if "verification_code" not in column_names:
        cursor.execute("ALTER TABLE users ADD COLUMN verification_code VARCHAR")

    if "code_sent_at" not in column_names:
        cursor.execute("ALTER TABLE users ADD COLUMN code_sent_at DATETIME")

    print("[users] Email-верификация настроена")


def migrate_create_admin_audit_log(cursor):
    """Создание таблицы журнала действий администратора"""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_audit_log'")
    if cursor.fetchone():
        print("[admin_audit_log] Таблица уже существует — пропуск")
        return

    print("[admin_audit_log] Создание таблицы...")
    cursor.execute("""
        CREATE TABLE admin_audit_log (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            admin_username VARCHAR NOT NULL,
            action VARCHAR NOT NULL,
            target_user_id INTEGER,
            details TEXT,
            ip_address VARCHAR,
            created_at DATETIME,
            FOREIGN KEY(admin_id) REFERENCES users (id)
        )
    """)
    cursor.execute("CREATE INDEX ix_admin_audit_log_created_at ON admin_audit_log (created_at)")
    print("[admin_audit_log] Готово")


def migrate_remove_recovery_code(cursor):
    """Удаление колонки recovery_code_enc из users"""
    cursor.execute("PRAGMA table_info(users)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]

    if "recovery_code_enc" not in column_names:
        print("[users] Колонка recovery_code_enc уже удалена — пропуск")
        return

    print("[users] Удаление колонки recovery_code_enc...")

    keep_columns = [col[1] for col in columns if col[1] != "recovery_code_enc"]
    cols_str = ", ".join(keep_columns)

    cursor.executescript(f"""
        ALTER TABLE users RENAME TO users_old;

        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            username VARCHAR NOT NULL UNIQUE,
            email VARCHAR NOT NULL UNIQUE,
            hashed_password VARCHAR NOT NULL,
            created_at DATETIME,
            is_verified BOOLEAN DEFAULT 0,
            verification_code VARCHAR,
            code_sent_at DATETIME,
            is_admin BOOLEAN DEFAULT 0,
            is_premium BOOLEAN DEFAULT 0,
            premium_expires_at DATETIME,
            storage_limit BIGINT DEFAULT 1073741824,
            is_restricted BOOLEAN DEFAULT 0
        );

        INSERT INTO users ({cols_str})
        SELECT {cols_str}
        FROM users_old;

        DROP TABLE users_old;
    """)

    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"[users] Готово. recovery_code_enc удалён, пользователей: {count}")


def migrate_create_registration_limits(cursor):
    """Создание таблицы лимитов регистрации по IP"""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='registration_limits'")
    if cursor.fetchone():
        print("[registration_limits] Таблица уже существует — пропуск")
        return

    print("[registration_limits] Создание таблицы...")
    cursor.execute("""
        CREATE TABLE registration_limits (
            ip_address VARCHAR NOT NULL PRIMARY KEY,
            registrations_count INTEGER DEFAULT 0,
            first_registration_at DATETIME NOT NULL
        )
    """)
    print("[registration_limits] Готово")


def migrate_add_cumulative_bytes(cursor):
    """Добавляет cumulative_bytes для O(1) freeze-check."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tracks'")
    if not cursor.fetchone():
        print("[tracks] Таблица не существует — пропуск cumulative_bytes")
        return

    cursor.execute("PRAGMA table_info(tracks)")
    column_names = [col[1] for col in cursor.fetchall()]
    if "cumulative_bytes" not in column_names:
        print("[tracks] Добавление колонки cumulative_bytes...")
        cursor.execute(
            "ALTER TABLE tracks ADD COLUMN cumulative_bytes INTEGER NOT NULL DEFAULT 0"
        )
        print("[tracks] cumulative_bytes добавлена")

    cursor.execute(
        "SELECT DISTINCT user_id FROM tracks ORDER BY user_id"
    )
    user_ids = [row[0] for row in cursor.fetchall()]
    for user_id in user_ids:
        cursor.execute(
            """
            SELECT id, file_size
            FROM tracks
            WHERE user_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (user_id,),
        )
        running = 0
        for track_id, file_size in cursor.fetchall():
            running += int(file_size or 0)
            cursor.execute(
                "UPDATE tracks SET cumulative_bytes = ? WHERE id = ?",
                (running, track_id),
            )
    print(f"[tracks] backfill cumulative_bytes для {len(user_ids)} пользователей")


def migrate_add_library_revision(cursor):
    """Добавляет library_revision для incremental sync клиентов."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone():
        print("[users] Таблица не существует — пропуск library_revision")
        return

    cursor.execute("PRAGMA table_info(users)")
    column_names = [col[1] for col in cursor.fetchall()]
    if "library_revision" in column_names:
        print("[users] Колонка library_revision уже есть — пропуск")
        return

    print("[users] Добавление колонки library_revision...")
    cursor.execute(
        "ALTER TABLE users ADD COLUMN library_revision INTEGER NOT NULL DEFAULT 1"
    )
    print("[users] library_revision добавлена")


def migrate():
    if not os.path.exists(DB_PATH):
        print("database.db не найден — миграция не нужна, таблицы будут созданы при старте")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        migrate_add_album_cover_art(cursor)
        migrate_add_album_cover_path(cursor)
        migrate_albums(cursor)
        migrate_remove_plain_password(cursor)
        migrate_add_email_verification(cursor)
        migrate_create_registration_limits(cursor)
        migrate_remove_recovery_code(cursor)
        migrate_create_admin_audit_log(cursor)
        migrate_add_library_revision(cursor)
        migrate_add_cumulative_bytes(cursor)
        conn.commit()
        print("\nВсе миграции выполнены успешно!")
    except Exception as e:
        conn.rollback()
        print(f"\nОшибка миграции: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
