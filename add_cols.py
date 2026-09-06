
import sqlite3

def add_col_if_not_exists(cursor, table, col, type_info):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_info}")
        print(f"Added {col}")
    except Exception as e:
        if "duplicate" in str(e):
            print(f"{col} already exists")
        else:
            print(f"Error adding {col}: {e}")

conn = sqlite3.connect("database.db")
c = conn.cursor()

add_col_if_not_exists(c, "users", "premium_expires_at", "DATETIME")
add_col_if_not_exists(c, "users", "recovery_code_enc", "TEXT")
add_col_if_not_exists(c, "users", "allow_youtube_import", "BOOLEAN DEFAULT 0")
add_col_if_not_exists(c, "radio_stations", "cover_path", "TEXT")
add_col_if_not_exists(c, "user_radio_stations", "cover_path", "TEXT")

conn.commit()
conn.close()
