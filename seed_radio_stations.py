# seed_radio_stations.py
# Запускать на проде: cd /var/www/sounduk_backend && python3 seed_radio_stations.py
# Сидирует базу популярными интернет-радиостанциями из открытого каталога Radio Browser.
# 2026-08-06: dead streams pruned — context/radio_catalog_cleanup_2026-08-06.md

import uuid
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
import models
from seed_radio_stations_gist import GIST_STATIONS

STATIONS = [
    # === News & Talk ===
    {"name": "BBC World Service", "stream_url": "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service", "genre": "News, Talk", "website": "https://www.bbc.co.uk/worldserviceradio"},
    {"name": "NPR 24 Hour Program Stream", "stream_url": "http://npr-ice.streamguys1.com/live.mp3", "genre": "News, Talk", "website": "https://www.npr.org/"},
    {"name": "CNN Radio", "stream_url": "https://tunein.cdnstream1.com/2868_96.mp3", "genre": "News", "website": "https://www.cnn.com/"},
    {"name": "Fox News Radio", "stream_url": "https://live.amperwave.net/direct/foxnewsradio-foxnewsradioaac-imc?source=fnr.web", "genre": "News", "website": "https://radio.foxnews.com/"},
    {"name": "LBC UK", "stream_url": "http://media-ice.musicradio.com/LBCUK", "genre": "News, Talk", "website": "https://www.lbc.co.uk/"},

    # === Top 40 / Pop ===
    {"name": "Capital FM (UK)", "stream_url": "https://media-ssl.musicradio.com/CapitalUK", "genre": "Pop, Top 40", "website": "https://www.capitalfm.com/"},
    {"name": "KIIS FM Los Angeles", "stream_url": "https://stream.revma.ihrhls.com/zc185", "genre": "Pop, Top 40", "website": "https://kiisfm.iheart.com/"},
    {"name": "Z100 New York", "stream_url": "https://stream.revma.ihrhls.com/zc1469", "genre": "Pop, Top 40", "website": "https://z100.iheart.com/"},
    {"name": "LOS 40 Principales España", "stream_url": "https://playerservices.streamtheworld.com/api/livestream-redirect/Los40.mp3", "genre": "Pop, Top 40", "website": "https://los40.com/"},
    {"name": "NRJ Hits", "stream_url": "https://streaming.nrjaudio.fm/ou7xugf3s5gi?origine=playernrj", "genre": "Pop, Hits", "website": "https://www.nrj.fr/"},

    # === Rock / Alternative ===
    {"name": "SWR3 (Germany)", "stream_url": "https://liveradio.swr.de/sw282p3/swr3/play.mp3", "genre": "Pop, Rock", "website": "https://www.swr3.de/"},
    {"name": "1LIVE (Germany)", "stream_url": "http://wdr-1live-live.icecast.wdr.de/wdr/1live/live/mp3/128/stream.mp3", "genre": "Rock, Top 40", "website": "https://www1.wdr.de/radio/1live/"},

    # === 80s / Oldies ===
    {"name": "80s80s Radio", "stream_url": "http://regiocast.streamabc.net/regc-80s80smweb2517500-mp3-192-1672667", "genre": "80s, Pop, Rock", "website": "https://www.80s80s.de/"},
    {"name": "Classic Vinyl HD", "stream_url": "https://icecast.walmradio.com:8443/classic", "genre": "Oldies, Easy Listening, Jazz", "website": "https://walmradio.com/classic"},

    # === Jazz ===
    {"name": "Adroit Jazz Underground", "stream_url": "https://icecast.walmradio.com:8443/jazz", "genre": "Jazz, Contemporary", "website": "https://walmradio.com/jazz"},
    {"name": "101 Smooth Jazz", "stream_url": "http://jking.cdnstream1.com/b22139_128mp3", "genre": "Smooth Jazz, Easy Listening", "website": "http://101smoothjazz.com/"},

    # === Electronic / Dance ===
    {"name": "Dance Wave!", "stream_url": "https://dancewave.online/dance.mp3", "genre": "Dance, Electronic, House, Trance", "website": "https://dancewave.online/"},

    # === Classical / Ambient ===
    {"name": "YourClassical – Peaceful Piano", "stream_url": "https://peacefulpiano.stream.publicradio.org/peacefulpiano.aac", "genre": "Classical, Piano, Relax", "website": "https://www.yourclassical.org/"},
    {"name": "Iowa Public Radio – Classical", "stream_url": "https://classical-stream.iowapublicradio.org/Classical.mp3", "genre": "Classical", "website": "https://www.iowapublicradio.org/"},

    # === Country ===

    # === French ===
    {"name": "France Inter", "stream_url": "https://stream.radiofrance.fr/franceinter/franceinter_hifi.m3u8?id=radiofrance", "genre": "General, Culture", "website": "https://www.radiofrance.fr/franceinter"},
    {"name": "RTL France", "stream_url": "https://live.m6radio.quortex.io/webM89Hc99XApzgfhXNX8ASN5/grouprtl/national/short/audio-64000/index.m3u8", "genre": "General, Talk", "website": "https://www.rtl.fr/"},
    {"name": "RMC France", "stream_url": "https://audio.bfmtv.com/rmcradio_128.mp3", "genre": "News, Sport, Talk", "website": "https://rmc.bfmtv.com/"},
    {"name": "Europe 1", "stream_url": "https://stream.europe1.fr/europe1.aac", "genre": "News, Talk", "website": "https://www.europe1.fr/"},
    {"name": "RFM France", "stream_url": "http://stream.rfm.fr/rfm.mp3", "genre": "Pop, Hits", "website": "https://www.rfm.fr/"},
    {"name": "Nostalgie France", "stream_url": "https://streaming.nrjaudio.fm/oua8a3w2dqao?origine=playernostalgie", "genre": "Oldies, Nostalgia", "website": "https://www.nostalgie.fr/"},
    {"name": "FUN Radio France", "stream_url": "http://icecast.funradio.fr/fun-1-44-128", "genre": "Dance, Electro", "website": "https://www.funradio.fr/"},
    {"name": "Skyrock", "stream_url": "http://icecast.skyrock.net/s/natio_mp3_128k", "genre": "Rap, Hip-Hop", "website": "https://skyrock.fm/"},

    # === Spanish ===
    {"name": "Cadena SER España", "stream_url": "http://playerservices.streamtheworld.com/api/livestream-redirect/CADENASER.mp3", "genre": "News, Talk", "website": "https://cadenaser.com/"},
    {"name": "esRadio España", "stream_url": "http://livestreaming.esradio.fm/stream64.mp3", "genre": "News, Talk", "website": "https://esradio.libertaddigital.com/"},

    # === Italian ===
    {"name": "Radio Italia Solo Musica Italiana", "stream_url": "https://radioitaliasmi.akamaized.net/hls/live/2093120/RISMI/stream01/streamPlaylist.m3u8", "genre": "Italian Pop", "website": "https://www.radioitalia.it/"},

    # === German ===
    {"name": "Deutschlandfunk", "stream_url": "https://st01.sslstream.dlf.de/dlf/01/128/mp3/stream.mp3?aggregator=web", "genre": "News, Culture", "website": "https://www.deutschlandfunk.de/"},

    # === BBC ===
    {"name": "BBC Radio 4", "stream_url": "http://as-hls-ww-live.akamaized.net/pool_55057080/live/ww/bbc_radio_fourfm/bbc_radio_fourfm.isml/bbc_radio_fourfm-audio%3d128000.norewind.m3u8", "genre": "News, Drama, Comedy", "website": "https://www.bbc.co.uk/radio4"},

    # === Chill / Eclectic ===
    {"name": "Radio Paradise (EU)", "stream_url": "http://stream-uk1.radioparadise.com/aac-320", "genre": "Eclectic, Rock, World", "website": "https://radioparadise.com/"},
    {"name": "MANGORADIO", "stream_url": "https://mangoradio.stream.laut.fm/mangoradio", "genre": "Variety, Music", "website": "https://mangoradio.de/"},
    {"name": "SomaFM: Groove Salad", "stream_url": "https://ice2.somafm.com/groovesalad-128-mp3", "genre": "Ambient, Chill, Downtempo", "website": "https://somafm.com/groovesalad/"},
    {"name": "SomaFM: Secret Agent", "stream_url": "https://ice2.somafm.com/secretagent-128-mp3", "genre": "Lounge, Jazz, Spy", "website": "https://somafm.com/secretagent/"},
    {"name": "SomaFM: Drone Zone", "stream_url": "https://ice2.somafm.com/dronezone-128-mp3", "genre": "Ambient, Drone, Atmospheric", "website": "https://somafm.com/dronezone/"},
] + GIST_STATIONS


def seed():
    db = SessionLocal()
    try:
        existing_urls = {s.stream_url for s in db.query(models.RadioStation).all()}
        now = datetime.utcnow()
        added = 0
        skipped = 0

        for s in STATIONS:
            if s["stream_url"] in existing_urls:
                skipped += 1
                continue
            station = models.RadioStation(
                id=uuid.uuid4().hex,
                name=s["name"],
                stream_url=s["stream_url"],
                genre=s.get("genre"),
                website=s.get("website"),
                created_at=now,
                updated_at=now,
            )
            db.add(station)
            added += 1

        db.commit()
        print(f"Done: added {added}, skipped {skipped} (already exist)")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
