"""Persons, unknown-face clusters, and per-face (re)assignment."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import matching
from ..db import get_conn

router = APIRouter(prefix="/api")


class NameIn(BaseModel):
    name: str


class AssignIn(BaseModel):
    person_id: int | None = None
    name: str | None = None  # create/reuse person by name


class FacePatch(BaseModel):
    person_id: int | None = None
    name: str | None = None
    clear: bool = False


def _person_for(conn, body) -> int:
    if body.person_id:
        return body.person_id
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "person_id or name required")
    row = conn.execute("SELECT id FROM persons WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO persons(name) VALUES (?)", (name,)).lastrowid


@router.get("/persons")
def list_persons():
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT pe.id, pe.name, COUNT(DISTINCT f.photo_id) photo_count, MIN(f.id) sample_face "
        "FROM persons pe LEFT JOIN faces f ON f.person_id=pe.id AND f.ignored=0 "
        "GROUP BY pe.id ORDER BY photo_count DESC, pe.name")]


@router.patch("/persons/{person_id}")
def rename_person(person_id: int, body: NameIn):
    conn = get_conn()
    conn.execute("UPDATE persons SET name=? WHERE id=?", (body.name.strip(), person_id))
    conn.commit()
    return {"ok": True}


@router.delete("/persons/{person_id}")
def delete_person(person_id: int):
    """Untags all their faces (photos are kept); faces go back to unknown."""
    conn = get_conn()
    conn.execute("UPDATE faces SET person_id=NULL, assigned_by=NULL WHERE person_id=?",
                 (person_id,))
    conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
    conn.commit()
    return {"ok": True}


@router.get("/clusters")
def list_clusters():
    conn = get_conn()
    clusters = conn.execute(
        "SELECT cluster_id id, COUNT(*) face_count, COUNT(DISTINCT photo_id) photo_count "
        "FROM faces WHERE cluster_id IS NOT NULL AND person_id IS NULL AND ignored=0 "
        "GROUP BY cluster_id ORDER BY face_count DESC").fetchall()
    out = []
    for c in clusters:
        samples = [r["id"] for r in conn.execute(
            "SELECT id FROM faces WHERE cluster_id=? AND person_id IS NULL AND ignored=0 "
            "ORDER BY det_score DESC LIMIT 4", (c["id"],))]
        out.append({**dict(c), "sample_faces": samples})
    return out


@router.post("/clusters/{cluster_id}/assign")
def assign_cluster(cluster_id: int, body: AssignIn):
    conn = get_conn()
    pid = _person_for(conn, body)
    conn.execute(
        "UPDATE faces SET person_id=?, assigned_by='user', cluster_id=NULL "
        "WHERE cluster_id=? AND person_id IS NULL AND ignored=0", (pid, cluster_id))
    conn.execute("DELETE FROM clusters WHERE id=?", (cluster_id,))
    conn.commit()
    matching.rematch_unknowns(conn)  # naming someone may resolve other unknowns
    return {"ok": True, "person_id": pid}


@router.patch("/faces/{face_id}")
def patch_face(face_id: int, body: FacePatch):
    conn = get_conn()
    if body.clear:
        conn.execute("UPDATE faces SET person_id=NULL, assigned_by=NULL WHERE id=?", (face_id,))
        conn.commit()
        return {"ok": True}
    pid = _person_for(conn, body)
    conn.execute("UPDATE faces SET person_id=?, assigned_by='user', cluster_id=NULL WHERE id=?",
                 (pid, face_id))
    conn.commit()
    matching.rematch_unknowns(conn)
    return {"ok": True, "person_id": pid}


@router.post("/faces/{face_id}/ignore")
def ignore_face(face_id: int):
    """Mark a detection as not-a-face (or a face to exclude from everything)."""
    conn = get_conn()
    conn.execute("UPDATE faces SET ignored=1, person_id=NULL, cluster_id=NULL WHERE id=?",
                 (face_id,))
    conn.commit()
    return {"ok": True}
