"""SQLite layer: schema + connection helpers. All tags live here; photo files are never modified."""
import os
import sqlite3
import threading
from pathlib import Path

# DPS_DATA_DIR env var overrides where the DB/thumbs/models live (used by tests)
DATA_DIR = Path(os.environ.get("DPS_DATA_DIR",
                               Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "photos.db"
THUMBS_DIR = DATA_DIR / "thumbs"
FACES_DIR = DATA_DIR / "thumbs" / "faces"
VIDEO_THUMBS_DIR = DATA_DIR / "thumbs" / "videos"
MODELS_DIR = DATA_DIR / "models"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL,
    width INTEGER, height INTEGER,
    taken_at TEXT,              -- ISO 'YYYY-MM-DD HH:MM:SS'
    gps_lat REAL, gps_lon REAL,
    camera TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    sharpness REAL,              -- Laplacian-variance blur score (higher = sharper)
    scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS faces (
    -- exactly one of photo_id/video_id is set — faces are shared across both
    -- media types so a person's identity (and matching/clustering) is the
    -- same whether they were tagged from a photo or a video.
    id INTEGER PRIMARY KEY,
    photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
    video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    frame_time REAL,            -- video faces only: seconds into the clip
    bbox_x REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
    det_score REAL,
    embedding BLOB NOT NULL,    -- 512 x float32, L2-normalized
    person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
    assigned_by TEXT,           -- 'auto' | 'user'
    ignored INTEGER NOT NULL DEFAULT 0,
    CHECK ((photo_id IS NOT NULL) + (video_id IS NOT NULL) = 1)
);
CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_video ON faces(video_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
CREATE TABLE IF NOT EXISTS person_exemplars (
    -- embeddings of user-confirmed faces; survive photo re-scans/purges so
    -- people never need re-tagging
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_exemplars_person ON person_exemplars(person_id);
CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS album_photos (
    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    PRIMARY KEY (album_id, photo_id)
);
CREATE TABLE IF NOT EXISTS clip_embeddings (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL     -- 512 x float32, L2-normalized
);
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY,
    query TEXT NOT NULL,
    searched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL,
    width INTEGER, height INTEGER,
    duration REAL,              -- seconds
    taken_at TEXT,               -- ISO 'YYYY-MM-DD HH:MM:SS' (from file mtime)
    gps_lat REAL, gps_lon REAL,  -- best-effort, from QuickTime '\xa9xyz' atom if present
    codec TEXT,                  -- fourcc, e.g. 'h264', 'hevc' — hevc often has no picture
                                  -- in Chrome/Edge without a codec extension (audio still plays)
    scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_videos_taken ON videos(taken_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS video_clip_embeddings (
    -- one row per sampled frame (videos.py aggregates via max-similarity)
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    frame_time REAL,
    embedding BLOB NOT NULL     -- 512 x float32, L2-normalized
);
CREATE INDEX IF NOT EXISTS idx_video_clip_video ON video_clip_embeddings(video_id);
"""


def get_conn() -> sqlite3.Connection:
    """One connection per thread (uvicorn worker threads + scanner thread)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    # must run before executescript(SCHEMA): that script's CREATE INDEX
    # statements reference faces.video_id, which doesn't exist on a
    # pre-video-support DB until this rebuild adds it
    _migrate_faces_table(conn)
    conn.executescript(SCHEMA)
    # migrations for DBs created before these columns existed
    try:
        conn.execute("ALTER TABLE albums ADD COLUMN auto TEXT")
    except sqlite3.OperationalError:
        pass  # column already present
    try:
        conn.execute("ALTER TABLE photos ADD COLUMN sharpness REAL")
    except sqlite3.OperationalError:
        pass  # column already present
    for stmt in ("ALTER TABLE videos ADD COLUMN gps_lat REAL",
                 "ALTER TABLE videos ADD COLUMN gps_lon REAL",
                 "ALTER TABLE videos ADD COLUMN codec TEXT"):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already present
    conn.commit()


def _migrate_faces_table(conn: sqlite3.Connection) -> None:
    """Pre-video-support DBs have faces.photo_id NOT NULL and no video_id/
    frame_time columns. SQLite can't relax a NOT NULL constraint via ALTER, so
    rebuild the table (no other table has a foreign key to faces.id, so this
    is safe): rename aside, recreate with the new shape, copy rows across as
    photo-origin faces, drop the old table."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(faces)")}
    if not cols or "video_id" in cols:
        return  # fresh install (already this shape) or already migrated
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.executescript("""
            ALTER TABLE faces RENAME TO faces_old;
            CREATE TABLE faces (
                id INTEGER PRIMARY KEY,
                photo_id INTEGER REFERENCES photos(id) ON DELETE CASCADE,
                video_id INTEGER REFERENCES videos(id) ON DELETE CASCADE,
                frame_time REAL,
                bbox_x REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
                det_score REAL,
                embedding BLOB NOT NULL,
                person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
                cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
                assigned_by TEXT,
                ignored INTEGER NOT NULL DEFAULT 0,
                CHECK ((photo_id IS NOT NULL) + (video_id IS NOT NULL) = 1)
            );
            INSERT INTO faces (id, photo_id, bbox_x, bbox_y, bbox_w, bbox_h, det_score,
                              embedding, person_id, cluster_id, assigned_by, ignored)
            SELECT id, photo_id, bbox_x, bbox_y, bbox_w, bbox_h, det_score,
                   embedding, person_id, cluster_id, assigned_by, ignored FROM faces_old;
            DROP TABLE faces_old;
            CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
            CREATE INDEX IF NOT EXISTS idx_faces_video ON faces(video_id);
            CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
            CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
        """)
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO app_settings(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
