"""One paginated endpoint powers every photo grid (timeline, person, album,
favorites, CLIP text search); filters combine."""
import datetime
import re

from fastapi import APIRouter
from pydantic import BaseModel

from .. import clip_search, geocode
from ..db import get_conn

_LOCATION_QUERY_RE = re.compile(r"^(.*?)\s+in\s+(.+)$", re.IGNORECASE)

router = APIRouter(prefix="/api")
PAGE = 120


@router.get("/timeline")
def timeline(cursor: str = "", person: int | None = None, album: int | None = None,
             favorites: int = 0, query: str = ""):
    conn = get_conn()

    if query.strip():
        # CLIP search: relevance order, cursor = integer offset into ranked ids.
        theme, place = _split_location_query(conn, query.strip())
        ranked = clip_search.search(conn, theme)
        if place:
            cities = geocode.photo_cities(conn)
            ranked = [pid for pid in ranked if cities.get(pid) == place]
        ranked = _apply_filters(conn, ranked, person, album, favorites)
        off = int(cursor) if cursor else 0
        page = ranked[off:off + PAGE]
        items = _photos_by_ids(conn, page)
        next_cursor = str(off + PAGE) if off + PAGE < len(ranked) else None
        return {"items": items, "next_cursor": next_cursor, "mode": "search",
                "theme": theme if place else None, "place": place}

    where, params = ["1=1"], []
    if person:
        where.append("p.id IN (SELECT photo_id FROM faces WHERE person_id=? AND ignored=0)")
        params.append(person)
    if album:
        where.append("p.id IN (SELECT photo_id FROM album_photos WHERE album_id=?)")
        params.append(album)
    if favorites:
        where.append("p.favorite=1")
    if cursor:
        taken, pid = cursor.rsplit("|", 1)
        where.append("(p.taken_at < ? OR (p.taken_at = ? AND p.id < ?))")
        params += [taken, taken, int(pid)]

    rows = conn.execute(
        f"SELECT p.id, p.taken_at, p.width, p.height, p.favorite FROM photos p "
        f"WHERE {' AND '.join(where)} ORDER BY p.taken_at DESC, p.id DESC LIMIT {PAGE + 1}",
        params).fetchall()
    items = [dict(r) for r in rows[:PAGE]]
    next_cursor = None
    if len(rows) > PAGE:
        last = items[-1]
        next_cursor = f"{last['taken_at']}|{last['id']}"
    return {"items": items, "next_cursor": next_cursor, "mode": "timeline"}


class SearchLogIn(BaseModel):
    query: str


@router.post("/search/log")
def log_search(body: SearchLogIn):
    q = body.query.strip()
    if q:
        get_conn().execute("INSERT INTO search_history(query) VALUES (?)", (q,))
        get_conn().commit()
    return {"ok": True}


@router.get("/search/suggestions")
def search_suggestions(limit: int = 8):
    """Past searches ranked by frequency, ties broken by recency — powers the
    autocomplete dropdown under the search box."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT query, COUNT(*) n, MAX(searched_at) last FROM search_history "
        "GROUP BY query COLLATE NOCASE ORDER BY n DESC, last DESC LIMIT ?", (limit,)).fetchall()
    return [r["query"] for r in rows]


@router.get("/timeline/years")
def timeline_years():
    """Photo counts per year, for the year-scrubber alongside the Photos grid."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT substr(taken_at,1,4) year, COUNT(*) c FROM photos "
        "WHERE taken_at IS NOT NULL GROUP BY year ORDER BY year DESC").fetchall()
    return [{"year": int(r["year"]), "count": r["c"]} for r in rows]


@router.get("/memories")
def memories():
    """Photos taken on today's month/day in previous years ('On This Day'),
    restricted to photos with at least one identified (named) face."""
    conn = get_conn()
    today = datetime.date.today()
    md = today.strftime("-%m-%d")
    rows = conn.execute(
        "SELECT id, taken_at, width, height, favorite, "
        "CAST(substr(taken_at, 1, 4) AS INTEGER) year "
        "FROM photos WHERE substr(taken_at, 5, 6) = ? "
        "AND id IN (SELECT photo_id FROM faces WHERE person_id IS NOT NULL AND ignored=0) "
        "ORDER BY taken_at DESC", (md,)).fetchall()
    by_year: dict[int, list[dict]] = {}
    for r in rows:
        year = r["year"]
        if year == today.year:
            continue  # only past years count as a "memory"
        by_year.setdefault(year, []).append(dict(r))
    return [{"year": y, "photos": by_year[y]} for y in sorted(by_year, reverse=True)]


def _split_location_query(conn, query: str) -> tuple[str, str | None]:
    """Parse queries like 'marriage in Ambala' into a CLIP theme part and a
    location filter — but only if the trailing place actually matches a
    geocoded location in the library, so an ordinary phrase that happens to
    contain " in " (e.g. "kids playing in the rain") isn't misread as one."""
    m = _LOCATION_QUERY_RE.match(query)
    if not m:
        return query, None
    theme, place = m.group(1).strip(), m.group(2).strip()
    if not theme or not place:
        return query, None
    cities = set(geocode.photo_cities(conn).values())
    place_lower = place.lower()
    match = next((c for c in cities if place_lower in c.lower() or c.lower() in place_lower), None)
    return (theme, match) if match else (query, None)


def _apply_filters(conn, ids: list[int], person, album, favorites) -> list[int]:
    if not (person or album or favorites) or not ids:
        return ids
    qmarks = ",".join("?" * len(ids))
    where, params = [f"p.id IN ({qmarks})"], list(ids)
    if person:
        where.append("p.id IN (SELECT photo_id FROM faces WHERE person_id=? AND ignored=0)")
        params.append(person)
    if album:
        where.append("p.id IN (SELECT photo_id FROM album_photos WHERE album_id=?)")
        params.append(album)
    if favorites:
        where.append("p.favorite=1")
    ok = {r["id"] for r in conn.execute(
        f"SELECT p.id FROM photos p WHERE {' AND '.join(where)}", params)}
    return [i for i in ids if i in ok]


def _photos_by_ids(conn, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    qmarks = ",".join("?" * len(ids))
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT id, taken_at, width, height, favorite FROM photos WHERE id IN ({qmarks})", ids)}
    return [rows[i] for i in ids if i in rows]
