"""GPS hotspot detection for the map view: named places ranked by photo count,
via the shared offline reverse-geocoder in geocode.py.
"""
import sqlite3

from . import geocode


def top_places(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    places: dict[str, dict] = {}
    for r, name in geocode.photo_locations(conn):
        p = places.setdefault(name, {"count": 0, "lat_sum": 0.0, "lon_sum": 0.0})
        p["count"] += 1
        p["lat_sum"] += r["gps_lat"]
        p["lon_sum"] += r["gps_lon"]

    out = [{"name": name, "count": p["count"],
            "lat": p["lat_sum"] / p["count"], "lon": p["lon_sum"] / p["count"]}
           for name, p in places.items()]
    out.sort(key=lambda x: -x["count"])
    return out[:limit]
