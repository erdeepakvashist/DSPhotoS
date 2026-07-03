"""Face -> person matching and clustering of unknown faces.

Tuning: raise thresholds if different people get merged; lower them if the
same person splits into many clusters.
"""
import sqlite3

import numpy as np

MATCH_THRESHOLD = 0.45    # cosine sim to a named person's centroid => auto-assign
CLUSTER_THRESHOLD = 0.55  # cosine sim to an unknown cluster's centroid => join it


def _to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _centroid(vecs: list[np.ndarray]) -> np.ndarray:
    c = np.mean(vecs, axis=0)
    return c / (np.linalg.norm(c) + 1e-9)


def person_centroids(conn: sqlite3.Connection) -> dict[int, np.ndarray]:
    rows = conn.execute(
        "SELECT person_id, embedding FROM faces WHERE person_id IS NOT NULL AND ignored=0"
    ).fetchall()
    groups: dict[int, list[np.ndarray]] = {}
    for r in rows:
        groups.setdefault(r["person_id"], []).append(_to_vec(r["embedding"]))
    return {pid: _centroid(v) for pid, v in groups.items()}


def cluster_centroids(conn: sqlite3.Connection) -> dict[int, np.ndarray]:
    rows = conn.execute(
        "SELECT cluster_id, embedding FROM faces "
        "WHERE cluster_id IS NOT NULL AND person_id IS NULL AND ignored=0"
    ).fetchall()
    groups: dict[int, list[np.ndarray]] = {}
    for r in rows:
        groups.setdefault(r["cluster_id"], []).append(_to_vec(r["embedding"]))
    return {cid: _centroid(v) for cid, v in groups.items()}


def best_match(emb: np.ndarray, centroids: dict[int, np.ndarray], thresh: float):
    """Return (id, similarity) of the best centroid above thresh, else (None, 0)."""
    best_id, best_sim = None, thresh
    for cid, c in centroids.items():
        sim = float(np.dot(emb, c))
        if sim >= best_sim:
            best_id, best_sim = cid, sim
    return best_id, best_sim


def assign_face(conn: sqlite3.Connection, face_id: int, emb: np.ndarray,
                persons: dict[int, np.ndarray], clusters: dict[int, np.ndarray]):
    """Match a new face to a person, else to/into an unknown cluster.

    Mutates the passed centroid dicts incrementally (cheap approximation; exact
    centroids are recomputed on the next scan).
    """
    pid, _ = best_match(emb, persons, MATCH_THRESHOLD)
    if pid is not None:
        conn.execute("UPDATE faces SET person_id=?, assigned_by='auto', cluster_id=NULL "
                     "WHERE id=?", (pid, face_id))
        return
    cid, _ = best_match(emb, clusters, CLUSTER_THRESHOLD)
    if cid is None:
        cid = conn.execute("INSERT INTO clusters DEFAULT VALUES").lastrowid
        clusters[cid] = emb
    else:
        c = clusters[cid] + emb
        clusters[cid] = c / (np.linalg.norm(c) + 1e-9)
    conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cid, face_id))


def rematch_unknowns(conn: sqlite3.Connection):
    """After a person gains faces (cluster named / manual tag), re-run matching over
    all unknown faces — naming Mom may resolve other clusters too. Never touches
    user-confirmed assignments."""
    persons = person_centroids(conn)
    if not persons:
        return
    rows = conn.execute(
        "SELECT id, embedding FROM faces WHERE person_id IS NULL AND ignored=0"
    ).fetchall()
    for r in rows:
        pid, _ = best_match(_to_vec(r["embedding"]), persons, MATCH_THRESHOLD)
        if pid is not None:
            conn.execute("UPDATE faces SET person_id=?, assigned_by='auto', cluster_id=NULL "
                         "WHERE id=?", (pid, r["id"]))
    _drop_empty_clusters(conn)
    conn.commit()


def _drop_empty_clusters(conn: sqlite3.Connection):
    conn.execute("DELETE FROM clusters WHERE id NOT IN "
                 "(SELECT DISTINCT cluster_id FROM faces WHERE cluster_id IS NOT NULL "
                 " AND person_id IS NULL AND ignored=0)")
