"""Auto-generated ("smart") albums, regenerated after every scan:

- Places:  photos grouped by city via offline reverse-geocoding of GPS EXIF.
- Trips:   multi-day bursts of photos taken away from the home city.
- Themes:  zero-shot CLIP matching against the stored image embeddings
           (parties, weddings, beach, ...).

Auto albums have albums.auto set (e.g. 'place:Bangalore'); user albums are
never touched. Deleting an auto album just means it reappears after the next
scan, so corrections belong in the constants below.
"""
import datetime
import sqlite3
from collections import Counter

import numpy as np

THEMES = {
    "🎉 Parties": "a photo of a party with people celebrating at night",
    "💒 Weddings": "a photo of a wedding ceremony with bride and groom",
    "🏖️ Beach": "a photo taken at the beach with sand and sea",
    "🏔️ Mountains": "a photo of mountains and hiking in nature",
    "🍽️ Food": "a close-up photo of a plate of delicious food",
    "🐾 Pets": "a photo of a pet dog or cat",
    "🤳 Selfies": "a close-up selfie photo of one person's face",
    "👨‍👩‍👧 Group photos": "a group photo of several people posing together",
    "🌇 Golden hour": "a photo taken at sunset or sunrise with warm golden light",
    "🏠 Indoors": "a photo taken indoors inside a room or building",
    "🌳 Outdoors": "a photo taken outdoors in nature or a street",
}
THEME_THRESHOLD = 0.24   # CLIP cosine floor for a photo to join a theme album
MIN_ALBUM_PHOTOS = 4     # don't create tiny albums
PLACE_MIN_PHOTOS = 5
TRIP_MAX_GAP_DAYS = 2    # consecutive photo-days this close belong to one trip
TRIP_MIN_DAYS = 2
TRIP_MIN_PHOTOS = 8


def regenerate(conn: sqlite3.Connection):
    from . import geocode
    conn.execute("DELETE FROM albums WHERE auto IS NOT NULL")
    _theme_albums(conn)
    cities = geocode.photo_cities(conn)
    _place_albums(conn, cities)
    _trip_albums(conn, cities)
    conn.commit()


def _create(conn, name: str, auto: str, photo_ids: list[int]):
    if len(photo_ids) < MIN_ALBUM_PHOTOS:
        return
    aid = conn.execute("INSERT INTO albums(name, auto, cover_photo_id) VALUES (?,?,?)",
                       (name, auto, photo_ids[0])).lastrowid
    conn.executemany("INSERT OR IGNORE INTO album_photos(album_id, photo_id) VALUES (?,?)",
                     [(aid, p) for p in photo_ids])


# ---- themes (CLIP zero-shot) ----

def _theme_albums(conn):
    rows = conn.execute("SELECT photo_id, embedding FROM clip_embeddings").fetchall()
    if not rows:
        return
    from . import clip_search
    ids = np.array([r["photo_id"] for r in rows])
    mat = np.frombuffer(b"".join(r["embedding"] for r in rows),
                        dtype=np.float32).reshape(len(rows), -1)
    names = list(THEMES)
    sims = np.stack([mat @ clip_search.embed_text(THEMES[n]) for n in names])  # theme x photo
    best = sims.argmax(axis=0)  # a photo joins only its best-matching theme
    for t, name in enumerate(names):
        mine = (best == t) & (sims[t] >= THEME_THRESHOLD)
        order = np.argsort(-sims[t][mine])
        _create(conn, name, f"theme:{name}", [int(i) for i in ids[mine][order]])


# ---- places (offline reverse geocoding via geocode.photo_cities) ----

def _place_albums(conn, cities: dict[int, str]):
    by_city: dict[str, list[int]] = {}
    for pid, city in cities.items():
        by_city.setdefault(city, []).append(pid)
    for city, pids in by_city.items():
        if len(pids) >= PLACE_MIN_PHOTOS:
            pids.sort(reverse=True)
            _create(conn, f"📍 {city}", f"place:{city}", pids)


# ---- trips (multi-day photo bursts away from home) ----

def _trip_albums(conn, cities: dict[int, str]):
    rows = conn.execute("SELECT id, taken_at FROM photos WHERE taken_at IS NOT NULL "
                        "ORDER BY taken_at").fetchall()
    if not rows:
        return
    home = Counter(cities.values()).most_common(1)[0][0] if cities else None

    # split the timeline into sessions of nearby photo-days
    sessions, cur = [], [rows[0]]
    for prev, r in zip(rows, rows[1:]):
        gap = (_day(r["taken_at"]) - _day(prev["taken_at"])).days
        if gap > TRIP_MAX_GAP_DAYS:
            sessions.append(cur)
            cur = []
        cur.append(r)
    sessions.append(cur)

    for s in sessions:
        days = (_day(s[-1]["taken_at"]) - _day(s[0]["taken_at"])).days + 1
        if days < TRIP_MIN_DAYS or len(s) < TRIP_MIN_PHOTOS:
            continue
        pids = [r["id"] for r in s]
        away = [cities[p] for p in pids if p in cities and cities[p] != home]
        place = Counter(away).most_common(1)[0][0] if away else None
        if home and cities and not away:
            continue  # multi-day burst at home isn't a trip
        when = _day(s[0]["taken_at"]).strftime("%b %Y")
        name = f"✈️ Trip to {place} — {when}" if place else f"✈️ Trip — {when}"
        _create(conn, name, f"trip:{s[0]['taken_at'][:10]}", list(reversed(pids)))


def _day(taken_at: str) -> datetime.date:
    return datetime.date.fromisoformat(taken_at[:10])
