# extract_covers.py
from mutagen import File as MutagenFile
from mutagen.id3 import APIC
from pathlib import Path
from database import SessionLocal
import models

db = SessionLocal()
tracks = db.query(models.Track).filter(models.Track.cover_path == None).all()

for track in tracks:
    file_path = Path(track.file_path)
    if not file_path.exists():
        continue
    try:
        audio = MutagenFile(str(file_path))
        cover_data = None
        if hasattr(audio, 'tags') and audio.tags:
            for tag in audio.tags.values():
                if isinstance(tag, APIC):
                    cover_data = tag.data
                    break
        if cover_data is None and hasattr(audio, 'pictures') and audio.pictures:
            cover_data = audio.pictures[0].data
        if cover_data:
            cover_file = file_path.parent / f"{track.id}.jpg"
            cover_file.write_bytes(cover_data)
            track.cover_path = str(cover_file)
            print(f"✅ {track.title}")
    except Exception as e:
        print(f"❌ {track.title}: {e}")

db.commit()
db.close()
