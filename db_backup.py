# db_backup.py - Бэкап и восстановление БД через S3
import fcntl
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from s3_utils import get_s3_client, S3_BUCKET_NAME

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
S3_DB_LATEST_KEY = "backups/database_latest.db"
STARTUP_LOCK_PATH = os.path.join(BASE_DIR, ".startup.lock")

BACKUP_INTERVAL_SECONDS = 60 * 30  # каждые 30 минут

_backup_thread = None
_stop_event = threading.Event()


class _StartupLock:
    """Один startup на хост (uvicorn --workers N иначе блокирует SQLite/S3)."""

    def __init__(self) -> None:
        self._handle = None
        self.acquired = False

    def __enter__(self) -> "_StartupLock":
        self._handle = open(STARTUP_LOCK_PATH, "w")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except BlockingIOError:
            self.acquired = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            if self.acquired:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()


def run_startup_once() -> bool:
    """S3 restore + periodic backup — только в одном uvicorn worker."""
    with _StartupLock() as lock:
        if not lock.acquired:
            print("[db_backup] ⏭ startup уже выполнен другим worker")
            return False
        download_db_from_s3()
        start_periodic_backup()
        return True


def upload_db_to_s3():
    """Загружает текущую БД на S3 с версионированием"""
    if not os.path.exists(DB_PATH):
        print("[db_backup] database.db не найден, пропуск бэкапа")
        return False

    # Копируем файл чтобы не читать во время записи SQLite
    tmp_path = DB_PATH + ".backup_tmp"
    try:
        shutil.copy2(DB_PATH, tmp_path)
        s3 = get_s3_client()

        # Загружаем как latest (для быстрого восстановления)
        with open(tmp_path, "rb") as f:
            s3.upload_fileobj(f, S3_BUCKET_NAME, S3_DB_LATEST_KEY)

        # Загружаем с меткой времени (история бэкапов)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        timestamped_key = f"backups/database_{timestamp}.db"
        with open(tmp_path, "rb") as f:
            s3.upload_fileobj(f, S3_BUCKET_NAME, timestamped_key)

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        print(f"[db_backup] ✅ БД загружена на S3: {timestamped_key} ({size_mb:.1f} MB)")
        return True

    except Exception as e:
        print(f"[db_backup] ❌ Ошибка загрузки на S3: {e}")
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def download_db_from_s3():
    """Скачивает последнюю БД с S3 при первом запуске приложения"""
    try:
        s3 = get_s3_client()

        # Проверяем есть ли бэкап на S3
        try:
            s3_obj = s3.head_object(Bucket=S3_BUCKET_NAME, Key=S3_DB_LATEST_KEY)
            s3_modified = s3_obj.get("LastModified")
        except:
            print("[db_backup] ⚠️  Бэкап на S3 не найден, использую локальную БД")
            return False

        # Если локальной БД нет или она старше S3 версии - скачиваем
        local_exists = os.path.exists(DB_PATH)
        local_modified = None

        if local_exists:
            local_modified = datetime.fromtimestamp(os.path.getmtime(DB_PATH))
            local_modified = local_modified.replace(tzinfo=None)
            s3_modified_naive = s3_modified.replace(tzinfo=None)

            if local_modified >= s3_modified_naive:
                print(f"[db_backup] 📦 Локальная БД актуальна, синхронизация не требуется")
                return False

        # Скачиваем с S3
        s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, DB_PATH)
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        print(f"[db_backup] ✅ БД восстановлена с S3 ({size_mb:.1f} MB)")
        return True

    except Exception as e:
        print(f"[db_backup] ❌ Ошибка загрузки с S3: {e}")
        return False


def _backup_loop():
    """Фоновый цикл периодического бэкапа с обработкой ошибок"""
    while not _stop_event.is_set():
        try:
            _stop_event.wait(BACKUP_INTERVAL_SECONDS)
            if not _stop_event.is_set():
                upload_db_to_s3()
        except Exception as e:
            print(f"[db_backup] ❌ Ошибка в цикле бэкапа: {e}")
            # Продолжаем работу даже если бэкап не удался


def start_periodic_backup():
    """Запускает фоновый поток для периодического бэкапа"""
    global _backup_thread
    _stop_event.clear()
    _backup_thread = threading.Thread(target=_backup_loop, daemon=True)
    _backup_thread.start()
    interval_min = BACKUP_INTERVAL_SECONDS // 60
    print(f"[db_backup] 🔄 Периодический бэкап запущен (каждые {interval_min} мин)")


def stop_periodic_backup():
    """Останавливает фоновый поток"""
    _stop_event.set()
    if _backup_thread:
        _backup_thread.join(timeout=5)
    print("[db_backup] 🛑 Периодический бэкап остановлен")
