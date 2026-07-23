# db_backup.py - Бэкап и восстановление БД через S3
import fcntl
import logging
import os
import re
import shutil
import threading
from datetime import datetime, timedelta, timezone

from s3_utils import get_s3_client, S3_BUCKET_NAME

logger = logging.getLogger("sounduk.db_backup")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
S3_DB_LATEST_KEY = "backups/database_latest.db"
S3_DB_PREFIX = "backups/"
# Timestamped keys: backups/database_YYYYMMDD_HHMMSS.db
_TIMESTAMPED_DB_RE = re.compile(
    r"^backups/database_(\d{8})_(\d{6})\.db$"
)
STARTUP_LOCK_PATH = os.path.join(BASE_DIR, ".startup.lock")

BACKUP_INTERVAL_SECONDS = 60 * 60 * 24  # раз в сутки
BACKUP_RETENTION_DAYS = 90

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
            logger.info("startup skipped (another worker holds lock)")
            return False
        threading.Thread(target=download_db_from_s3, daemon=True).start()
        start_periodic_backup()
        return True


def prune_old_backups(days: int = BACKUP_RETENTION_DAYS) -> int:
    """
    Удаляет timestamped бэкапы старше `days` дней.
    Никогда не трогает backups/database_latest.db.
    Возвращает число удалённых объектов. Ошибки логирует, не пробрасывает.
    """
    deleted = 0
    try:
        s3 = get_s3_client()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        paginator = s3.get_paginator("list_objects_v2")
        to_delete: list[str] = []

        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_DB_PREFIX):
            for obj in page.get("Contents") or []:
                key = obj.get("Key") or ""
                if key == S3_DB_LATEST_KEY:
                    continue
                if not _TIMESTAMPED_DB_RE.match(key):
                    continue
                last_modified = obj.get("LastModified")
                if last_modified is None:
                    continue
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)
                if last_modified < cutoff:
                    to_delete.append(key)

        for key in to_delete:
            try:
                s3.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
                deleted += 1
            except Exception as e:
                logger.error("prune delete failed key=%s error=%s", key, e)

        logger.info(
            "prune old backups done retention_days=%s deleted=%s candidates=%s",
            days,
            deleted,
            len(to_delete),
        )
    except Exception as e:
        logger.error("prune old backups failed error=%s", e)
    return deleted


def upload_db_to_s3():
    """Загружает текущую БД на S3 с версионированием и prune старых копий."""
    if not os.path.exists(DB_PATH):
        logger.warning("database.db not found, skip backup")
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
        logger.info("db uploaded to S3 key=%s size_mb=%.1f", timestamped_key, size_mb)

        prune_old_backups(BACKUP_RETENTION_DAYS)
        return True

    except Exception as e:
        logger.error("db upload to S3 failed error=%s", e)
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _file_sha256(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_db_from_s3():
    """Скачивает последнюю БД с S3 при старте, если локальная старше или отсутствует.

    Если локальный файл новее S3 по UTC mtime, но sha отличается — оставляем local
    (не затираем свежие данные старым бэкапом).
    """
    try:
        s3 = get_s3_client()

        try:
            s3_obj = s3.head_object(Bucket=S3_BUCKET_NAME, Key=S3_DB_LATEST_KEY)
            s3_modified = s3_obj.get("LastModified")
            s3_size = int(s3_obj.get("ContentLength") or 0)
            s3_etag = (s3_obj.get("ETag") or "").strip('"')
        except Exception:
            logger.warning("S3 backup not found, using local db")
            return False

        local_exists = os.path.exists(DB_PATH)

        if not local_exists:
            s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, DB_PATH)
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            logger.info("db restored from S3 (no local) size_mb=%.1f", size_mb)
            return True

        local_modified = datetime.fromtimestamp(
            os.path.getmtime(DB_PATH), tz=timezone.utc
        )
        if s3_modified.tzinfo is None:
            s3_modified_utc = s3_modified.replace(tzinfo=timezone.utc)
        else:
            s3_modified_utc = s3_modified.astimezone(timezone.utc)

        local_size = os.path.getsize(DB_PATH)

        # Local strictly newer → never clobber with older S3 snapshot.
        if local_modified > s3_modified_utc:
            logger.info(
                "local db newer than S3 (utc); keep local local=%s s3=%s etag=%s",
                local_modified.isoformat(),
                s3_modified_utc.isoformat(),
                s3_etag,
            )
            return False

        # Local older → restore from S3.
        if local_modified < s3_modified_utc:
            s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, DB_PATH)
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            logger.info(
                "db restored from S3 (local older) size_mb=%.1f local=%s s3=%s",
                size_mb,
                local_modified.isoformat(),
                s3_modified_utc.isoformat(),
            )
            return True

        # Same mtime second-resolution / equal: compare content.
        if local_size != s3_size:
            s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, DB_PATH)
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            logger.info(
                "db restored from S3 (same mtime, size differs) size_mb=%.1f",
                size_mb,
            )
            return True

        tmp_check = DB_PATH + ".restore_check"
        try:
            s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, tmp_check)
            local_sha = _file_sha256(DB_PATH)
            s3_sha = _file_sha256(tmp_check)
            if local_sha == s3_sha:
                logger.info(
                    "local db up to date (utc mtime+sha), skip S3 restore etag=%s",
                    s3_etag,
                )
                return False
            # Equal mtime, different sha: prefer S3 as canonical backup channel.
            os.replace(tmp_check, DB_PATH)
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            logger.warning(
                "db restored from S3 (equal mtime, sha differs) size_mb=%.1f",
                size_mb,
            )
            return True
        finally:
            if os.path.exists(tmp_check):
                try:
                    os.remove(tmp_check)
                except OSError:
                    pass

    except Exception as e:
        logger.error("db restore from S3 failed error=%s", e)
        return False


def _backup_loop():
    """Фоновый цикл периодического бэкапа с обработкой ошибок"""
    while not _stop_event.is_set():
        try:
            _stop_event.wait(BACKUP_INTERVAL_SECONDS)
            if not _stop_event.is_set():
                upload_db_to_s3()
        except Exception as e:
            logger.error("backup loop error=%s", e)
            # Продолжаем работу даже если бэкап не удался


def start_periodic_backup():
    """Запускает фоновый поток для периодического бэкапа"""
    global _backup_thread
    _stop_event.clear()
    _backup_thread = threading.Thread(target=_backup_loop, daemon=True)
    _backup_thread.start()
    interval_min = BACKUP_INTERVAL_SECONDS // 60
    logger.info(
        "periodic backup started interval_min=%s retention_days=%s",
        interval_min,
        BACKUP_RETENTION_DAYS,
    )


def stop_periodic_backup():
    """Останавливает фоновый поток"""
    _stop_event.set()
    if _backup_thread:
        _backup_thread.join(timeout=5)
    logger.info("periodic backup stopped")
