"""Near-duplicate photo detection via CLIP embedding cosine similarity."""
import sqlite3

import numpy as np

DUP_THRESHOLD = 0.97  # CLIP cosine floor for "same moment" duplicates/near-dupes


def find_duplicate_groups(conn: sqlite3.Connection, threshold: float = DUP_THRESHOLD) -> list[list[int]]:
    """Groups of photo ids (size >= 2) whose CLIP embeddings are near-identical."""
    rows = conn.execute("SELECT photo_id, embedding FROM clip_embeddings ORDER BY photo_id").fetchall()
    if len(rows) < 2:
        return []
    ids = [r["photo_id"] for r in rows]
    mat = np.frombuffer(b"".join(r["embedding"] for r in rows),
                        dtype=np.float32).reshape(len(rows), -1)
    sims = mat @ mat.T

    parent = list(range(len(ids)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    n = len(ids)
    for i in range(n):
        for off in np.where(sims[i, i + 1:] >= threshold)[0]:
            union(i, i + 1 + int(off))

    groups: dict[int, list[int]] = {}
    for idx, pid in enumerate(ids):
        groups.setdefault(find(idx), []).append(pid)
    return [g for g in groups.values() if len(g) > 1]
