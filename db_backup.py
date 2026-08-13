# db_backup.py - Бэкап и восстановление БД через S3
import fcntl
import logging
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone

from s3_utils import get_s3_client, S3_BUCKET_NAME

logger = logging.getLogger("sounduk.db_backup")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
S3_DB_LATEST_KEY = "backups/database_latest.db"
S3_DB_PREFIX = "backups/"
STARTUP_LOCK_PATH = os.path.join(BASE_DIR, ".startup.lock")

BACKUP_INTERVAL_SECONDS = 60 * 60 * 24  # раз в сутки
BACKUP_RETENTION_DAYS = 7  # rolling week: ~7×1MB < 10MB

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
    Чистит backups/:
    1) удаляет всё старше `days` дней (кроме database_latest.db);
    2) в оставшемся окне оставляет один объект на UTC-день (largest),
       плюс database_latest — чтобы при частых upload'ах вес оставался < ~10MB.
    """
    deleted = 0
    try:
        s3 = get_s3_client()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        paginator = s3.get_paginator("list_objects_v2")
        to_delete: list[str] = []
        by_day: dict[str, list[tuple[int, str, datetime]]] = {}

        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_DB_PREFIX):
            for obj in page.get("Contents") or []:
                key = obj.get("Key") or ""
                if key == S3_DB_LATEST_KEY or key == S3_DB_PREFIX.rstrip("/"):
                    continue
                last_modified = obj.get("LastModified")
                if last_modified is None:
                    continue
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)
                else:
                    last_modified = last_modified.astimezone(timezone.utc)
                if last_modified < cutoff:
                    to_delete.append(key)
                    continue
                day = last_modified.date().isoformat()
                by_day.setdefault(day, []).append(
                    (int(obj.get("Size") or 0), key, last_modified)
                )

        # One snapshot per day (prefer largest, then newest).
        for items in by_day.values():
            items.sort(key=lambda x: (x[0], x[2]), reverse=True)
            for _, key, _ in items[1:]:
                to_delete.append(key)

        for i in range(0, len(to_delete), 1000):
            chunk = to_delete[i : i + 1000]
            try:
                resp = s3.delete_objects(
                    Bucket=S3_BUCKET_NAME,
                    Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
                )
                errors = resp.get("Errors") or []
                deleted += len(chunk) - len(errors)
                for err in errors:
                    logger.error(
                        "prune delete failed key=%s code=%s msg=%s",
                        err.get("Key"),
                        err.get("Code"),
                        err.get("Message"),
                    )
            except Exception as e:
                logger.error("prune batch delete failed error=%s", e)
                for key in chunk:
                    try:
                        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
                        deleted += 1
                    except Exception as e2:
                        logger.error("prune delete failed key=%s error=%s", key, e2)

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
    """Загружает текущую БД на S3: сначала prune старше недели, затем новая копия.

    Порядок: (1) удалить timestamped бэкапы старше BACKUP_RETENTION_DAYS,
    (2) записать database_latest + timestamped. Так backups/ остаётся < ~10MB.
    """
    if not os.path.exists(DB_PATH):
        logger.warning("database.db not found, skip backup")
        return False

    # Копируем файл чтобы не читать во время записи SQLite
    tmp_path = DB_PATH + ".backup_tmp"
    try:
        shutil.copy2(DB_PATH, tmp_path)
        s3 = get_s3_client()

        # 1) Сначала убрать недельной давности (и старше)
        prune_old_backups(BACKUP_RETENTION_DAYS)

        # 2) Сохранить новую: latest + timestamped
        with open(tmp_path, "rb") as f:
            s3.upload_fileobj(f, S3_BUCKET_NAME, S3_DB_LATEST_KEY)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        timestamped_key = f"backups/database_{timestamp}.db"
        with open(tmp_path, "rb") as f:
            s3.upload_fileobj(f, S3_BUCKET_NAME, timestamped_key)

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        logger.info("db uploaded to S3 key=%s size_mb=%.1f", timestamped_key, size_mb)
        return True

    except Exception as e:
        logger.error("db upload to S3 failed error=%s", e)
        return False
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def download_db_from_s3():
    """Скачивает БД с S3 при старте только если локального файла нет.

    Если `database.db` уже есть — никогда не затираем его из S3 на старте.
    S3 LastModified = время upload, не возраст данных: чужой/старый хост
    с тем же бакетом может «отравить» latest свежим upload'ом старого файла.
    Disaster recovery — вручную (остановить сервис, заменить файл, upload_db_to_s3).
    """
    try:
        if os.path.exists(DB_PATH):
            local_size = os.path.getsize(DB_PATH)
            logger.info(
                "keep local; auto-restore disabled when local exists size_mb=%.1f",
                local_size / (1024 * 1024),
            )
            return False

        s3 = get_s3_client()
        try:
            s3.head_object(Bucket=S3_BUCKET_NAME, Key=S3_DB_LATEST_KEY)
        except Exception:
            logger.warning("S3 backup not found, no local db")
            return False

        s3.download_file(S3_BUCKET_NAME, S3_DB_LATEST_KEY, DB_PATH)
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
        logger.info("db restored from S3 (no local) size_mb=%.1f", size_mb)
        return True

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
