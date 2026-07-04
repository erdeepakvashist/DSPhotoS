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
| 11 | Mobile LAN photo upload | ⬜ | |
| 12 | Smart face-level dedup (blurry duplicate face flagging) | ⬜ | |

## Notes per feature

1. **Expanded smart albums** — extend `THEMES` in `smart_albums.py` with new CLIP
   zero-shot prompts (pets, selfies, sunset, indoor/outdoor, group photos).
2. **On This Day** — new `/api/on-this-day` endpoint using `taken_at` month/day
   match across years; UI card on the Photos tab.
3. **Duplicates** — cosine-similarity clustering over existing `clip_embeddings`;
   new `/api/duplicates` endpoint + UI panel to review. "Archive the others"
   moves non-kept copies into an `Archive` folder beside the originals
   (`app/archive.py`) — files are moved, never deleted, and the scanner skips
   `Archive` folders so they don't come back.
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
   used to pick the "keep" copy in duplicate groups (item 3).
7. **Privacy blur** — endpoint to render a copy of a photo with untagged/all
   faces pixelated, for safe sharing.
8. **Metadata export** — write person names + album names into EXIF/XMP
   (piexif) or export a CSV, on demand from Settings.
9. **Story sequences** — group each detected "trip"/day burst into an ordered
   recap sequence exposed via a lightweight viewer.
10. **Search suggestions** — log query text, surface top recent/frequent
    queries as autocomplete under the search box.
11. **Mobile LAN upload** — `/upload` page + endpoint reachable from phone
    browsers on the same LAN, saved into a watched folder.
12. **Face-level dedup** — within near-duplicate photo groups, prefer the photo
    whose faces have the highest `det_score` (sharpest) when suggesting which
    to keep.
