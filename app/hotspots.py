"""GPS hotspot detection for the map view: named places ranked by photo count,
via the same offline reverse-geocoder smart_albums.py uses for place albums.
"""
import sqlite3


def top_places(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT id, gps_lat, gps_lon FROM photos "
        "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL").fetchall()
    if not rows:
        return []
    import reverse_geocoder as rg
    # mode=1: single-threaded — the default uses multiprocessing, which breaks
    # inside a Windows server thread
    results = rg.search([(r["gps_lat"], r["gps_lon"]) for r in rows], mode=1)

    places: dict[str, dict] = {}
    for r, res in zip(rows, results):
        name = res["name"]
        p = places.setdefault(name, {"count": 0, "lat_sum": 0.0, "lon_sum": 0.0})
        p["count"] += 1
        p["lat_sum"] += r["gps_lat"]
        p["lon_sum"] += r["gps_lon"]

    out = [{"name": name, "count": p["count"],
            "lat": p["lat_sum"] / p["count"], "lon": p["lon_sum"] / p["count"]}
           for name, p in places.items()]
    out.sort(key=lambda x: -x["count"])
    return out[:limit]
