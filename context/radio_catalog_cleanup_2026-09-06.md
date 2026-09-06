# Radio catalog cleanup (2026-09-06)

## Что сделали

Повторный probe всех stream URL на проде `178.72.184.68`.

| | |
|--|--|
| Было | **148** |
| Живые | **147** |
| Удалены | **1** |
| Backup БД | `backups/database_radio_cleanup_20260906_075851.db` |

Удалена: **RADIO SPB1 Trance** (`https://myradio24.org/2666`) — HTTP 404.

Seed: убрана из `seed_radio_stations_gist.py`. `user_radio_stations` не трогали.
