"""SQLite layer: schema + connection helpers. All tags live here; photo files are never modified."""
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "photos.db"
THUMBS_DIR = DATA_DIR / "thumbs"
FACES_DIR = DATA_DIR / "thumbs" / "faces"
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
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    bbox_x REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
    det_score REAL,
    embedding BLOB NOT NULL,    -- 512 x float32, L2-normalized
    person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
    assigned_by TEXT,           -- 'auto' | 'user'
    ignored INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
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
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    get_conn().executescript(SCHEMA)
    get_conn().commit()
