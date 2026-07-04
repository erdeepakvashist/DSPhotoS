# Feature Backlog — Futuristic Photo Management

Tracks the 12 features proposed for DS PhotoS. Each has its own commit on
`feature/backlog`. Status is updated as work lands — ask "what's the backlog
status" any time to get a summary of this file.

Legend: ⬜ Not started · 🔄 In progress · ✅ Done · ⏸️ Deferred

| # | Feature | Status | Commit |
|---|---------|--------|--------|
| 1 | Expanded smart albums (pets, selfies, sunsets, indoor/outdoor, groups) | ⬜ | |
| 2 | "On This Day" memory timeline | ⬜ | |
| 3 | Duplicate & near-duplicate photo detection + Archive cleanup | ⬜ | |
| 4 | Location hotspot clustering (map view) | ⬜ | |
| 5 | Search by face — click any face in the lightbox | ⬜ | |
| 6 | Automated photo quality scoring (blur/exposure) | ⬜ | |
| 7 | Privacy face-blur toggle for sharing | ⬜ | |
| 8 | Metadata export (EXIF/XMP keywords, CSV) | ⬜ | |
| 9 | Story sequences — auto day/trip recap albums | ⬜ | |
| 10 | Personalized search suggestions | ⬜ | |
| 11 | Mobile LAN photo upload | ⏸️ deferred | |
| 12 | Smart face-level dedup (blurry duplicate face flagging) | ✅ merged into 3+6 | 687025a |

## Notes per feature

1. **Expanded smart albums** — extend `THEMES` in `smart_albums.py` with new CLIP
   zero-shot prompts (pets, selfies, sunset, indoor/outdoor, group photos).
2. **On This Day** — new `/api/on-this-day` endpoint using `taken_at` month/day
   match across years; UI card on the Photos tab.
3. **Duplicates** — cosine-similarity clustering over existing `clip_embeddings`;
   new `/api/duplicates` endpoint + UI panel to review. "Archive the others"
   moves non-kept copies into an `Archive` folder beside the originals
   (`app/archive.py`) — files are moved, never deleted, and the scanner skips
   `Archive` folders so they don't come back. Settings > Archive folder lets
   the user instead pick one fixed destination for all archived photos
   (`app_settings` key-value table, `GET/POST/DELETE /api/settings/archive-folder`);
   the scanner skips that exact path too, wherever it lives, not just
   folders literally named "Archive".
4. **Location hotspots** — `app/hotspots.py` reverse-geocodes GPS EXIF into named
   places (reusing the same offline geocoder as smart_albums.py) and ranks them
   by photo count; the map view gets a "Top places" side panel plus
   density circles sized by `sqrt(count)`.
5. **Search by face** — new `GET /api/faces/{id}/similar` reuses the ranking
   logic behind `/api/search/face` (factored into `_search_by_embedding`) but
   looks up an existing face's stored embedding instead of a camera capture.
   The lightbox face menu gained a "Find photos with this face" action.
6. **Quality scoring** — Laplacian-variance blur score computed per photo during
   scan (reusing the already-decoded RGB array, `photos.sharpness` column) and
   surfaced via a new `✨ Best` tab (`/api/best-shots`) sorted by sharpness. Also
   used to pick the "keep" copy in duplicate groups (item 3). Photos indexed
   before this existed have `sharpness IS NULL`; Settings > Scanning shows a
   "Score existing photos for quality" button (`POST
   /api/scan/backfill-sharpness`) that scores just those photos — reads +
   computes only, no re-running face detection or CLIP.
7. **Privacy blur** — `app/privacy.py` renders a pixelated copy of a photo
   (`GET /api/photos/{id}/share?mode=untagged|all`); the lightbox gained a
   🛡️ Share button offering "blur only unnamed faces" or "blur everyone".
   Downloads only — the original file is never touched.
8. **Metadata export** — `app/export.py` exports a CSV (path, date, people,
   albums, favorite, GPS) via a Settings button. Deliberately CSV-only, not
   in-place EXIF/XMP writes — the README's "original files are never
   modified" invariant rules that out.
9. **Story sequences** — trips/places are already grouped into albums by
   smart_albums.py; added `GET /api/albums/{id}/photos` (full ordered list)
   plus a "▶ Play as story" fullscreen auto-advancing slideshow (any album,
   not just auto-generated ones), with progress segments and pause/prev/next.
10. **Search suggestions** — new `search_history` table logs each submitted
    query (`POST /api/search/log`); `GET /api/search/suggestions` ranks past
    queries by frequency then recency. A dropdown under the search box shows
    them on focus (when the box is empty).
11. **Mobile LAN upload** — deferred. The app is deliberately bound to
    127.0.0.1 only with zero authentication (see SECURITY.md / README:
    "everything stays on your machine"); making it phone-reachable means
    binding to 0.0.0.0, which would expose every photo, face tag, and the
    scan/quit controls to anyone on the LAN. Needs a real auth story (PIN
    gate, at minimum) before it's safe to build — deferred rather than
    shipped without one.
12. **Face-level dedup** — within near-duplicate photo groups, prefer the photo
    whose faces have the highest `det_score` (sharpest) when suggesting which
    to keep.
