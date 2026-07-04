"""Shared offline reverse-geocoding: GPS EXIF -> named place. Used by smart
place/trip albums, the map's hotspot panel, and location-aware search
("marriage in Ambala").
"""
import sqlite3


def photo_locations(conn: sqlite3.Connection) -> list[tuple[sqlite3.Row, str]]:
    """(photo row, city name) for every GPS-tagged photo."""
    rows = conn.execute("SELECT id, gps_lat, gps_lon FROM photos "
                        "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL").fetchall()
    if not rows:
        return []
    import reverse_geocoder as rg
    # mode=1: single-threaded — the default uses multiprocessing, which breaks
    # inside a Windows server thread
    results = rg.search([(r["gps_lat"], r["gps_lon"]) for r in rows], mode=1)
    return list(zip(rows, (res["name"] for res in results)))


def photo_cities(conn: sqlite3.Connection) -> dict[int, str]:
    """photo_id -> 'City' for every GPS-tagged photo."""
    return {r["id"]: name for r, name in photo_locations(conn)}
