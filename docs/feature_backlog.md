# Feature Backlog — Futuristic Photo Management

Tracks the 12 features proposed for DS PhotoS. Each has its own commit on
`feature/backlog`. Status is updated as work lands — ask "what's the backlog
status" any time to get a summary of this file.

Legend: ⬜ Not started · 🔄 In progress · ✅ Done · ⏸️ Deferred

| # | Feature | Status | Commit |
|---|---------|--------|--------|
| 1 | Expanded smart albums (pets, selfies, sunsets, indoor/outdoor, groups) | ⬜ | |
| 2 | "On This Day" memory timeline | ⬜ | |
| 3 | Duplicate & near-duplicate photo detection | ⬜ | |
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
   new `/api/duplicates` endpoint + UI panel to review/delete.
4. **Location hotspots** — cluster GPS points (grid/geohash) server-side, surface
   as marker clusters/heat circles on the existing Leaflet map.
5. **Search by face** — lightbox face boxes become clickable, reusing
   `matching`/embedding search already backing `/api/search/face`.
6. **Quality scoring** — Laplacian-variance blur + histogram exposure computed
   during scan, stored per photo, surfaced as a sort/filter.
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
