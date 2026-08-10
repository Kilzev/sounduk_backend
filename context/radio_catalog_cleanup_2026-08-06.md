# Radio catalog cleanup (2026-08-06)

## Что сделали

На проде `178.72.184.68` (`/var/www/sounduk_backend`) проверили все URL из `radio_stations` HTTP GET (timeout 12s, follow redirects, UA браузера/VLC, чтение первых 2 KB).

| | |
|--|--|
| Было | **181** |
| Живые | **148** |
| Удалены | **33** |
| Backup БД | `backups/database_radio_cleanup_20260806_144617.db` |
| Список | [`radio_deleted_2026-08-06.json`](./radio_deleted_2026-08-06.json) |

Seed-скрипты в репо тоже почищены (`seed_radio_stations.py`, `seed_radio_stations_gist.py`), чтобы повторный `python3 seed_radio_stations.py` не вернул мёртвые URL.

## Почему удаляли

Критерии «не работает» с прод-сервера:

- **HTTP 404 / Not Available** — каналы Radio Record, BBC Radio 3 HLS
- **HTTP 403** — Lite Rock (StreamTheWorld)
- **DNS / no route / connection refused** — хост мёртв
- **Timeout / SSL verify fail** — поток недоступен с прод-сети (и обычно не играет в клиенте)

## Группы удалённых

1. **Radio Record (закрытые/устаревшие каналы, 404):** A State of Trance, Afro House, Beach Party, DJ Gvozd, DJ Цветкоff, Feel, Lady Waks, Lo-Fi House, Martin Garrix, Nejtrino & Baur, Nu Dance, Oliver Heldens, Record Classix, Record Club Show, Russian Hits, Summer Lounge, Ultra Music Festival + старый HTTP `Record Супердискотека 90-х` (`online.radiorecord.ru:8102`).
2. **RU ретро / локальные (timeout / unreachable):** Золотой Век, Подмосковные вечера, Ностальжи, НостальгияФМ, Радио 1945, Лучшие Песни, Megapolis FM, Радиола Саратов, Wasteland FM, Swing Radio, Retrowave.One.
3. **Intl (timeout / 403 / 404):** France Culture, France Info, Lite Rock WEZN, BBC Radio 3.

## Замечания

- HTTPS-каналы Record, которые отвечали 200, **оставлены**.
- France Inter / другие FR, прошедшие probe, **оставлены**.
- Пользовательские станции (`user_radio_stations`) **не трогали**.
- Каталог отдаётся клиенту через `GET /api/radio/stations` — после pull-to-refresh / silent refresh список обновится без деплоя бэкенда (только DELETE в SQLite).

## Как повторить

```bash
ssh -i ~/.ssh/sounduk_cursor root@178.72.184.68
cd /var/www/sounduk_backend
# probe → /tmp/radio_probe_bad.json, затем DELETE по id
```
