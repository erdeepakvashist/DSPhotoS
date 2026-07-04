"""CSV export of the app's tags/metadata — path, people, albums, favorites,
GPS — for use in other tools. Never writes to the original photo files
themselves (see README: "Original photo files are never modified").
"""
import csv
import io
import sqlite3


def export_csv(conn: sqlite3.Connection) -> str:
    photos = conn.execute(
        "SELECT id, path, taken_at, favorite, gps_lat, gps_lon FROM photos "
        "ORDER BY taken_at").fetchall()
    people_by_photo: dict[int, list[str]] = {}
    for r in conn.execute(
            "SELECT f.photo_id, pe.name FROM faces f JOIN persons pe ON pe.id=f.person_id "
            "WHERE f.ignored=0 AND f.person_id IS NOT NULL"):
        people_by_photo.setdefault(r["photo_id"], []).append(r["name"])
    albums_by_photo: dict[int, list[str]] = {}
    for r in conn.execute(
            "SELECT ap.photo_id, a.name FROM album_photos ap JOIN albums a ON a.id=ap.album_id"):
        albums_by_photo.setdefault(r["photo_id"], []).append(r["name"])

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["path", "taken_at", "favorite", "people", "albums", "gps_lat", "gps_lon"])
    for p in photos:
        w.writerow([
            p["path"], p["taken_at"] or "", "yes" if p["favorite"] else "",
            "; ".join(sorted(people_by_photo.get(p["id"], []))),
            "; ".join(sorted(albums_by_photo.get(p["id"], []))),
            p["gps_lat"] or "", p["gps_lon"] or "",
        ])
    return buf.getvalue()
