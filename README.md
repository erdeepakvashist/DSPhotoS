# DS PhotoS

A locally hosted, Google Photos-style web app for your own photo folders.

- **Face search & tagging** — every face in every photo is detected and embedded
  (InsightFace buffalo_l models via onnxruntime, CPU). Photos with multiple people
  are tagged against each identified person.
- **Auto-clustering** — unknown faces are grouped; name a group once
  ("This is Mom") and all its photos are tagged. New photos auto-match.
- **Timeline** — chronological grid with month headers (EXIF dates).
- **Text search** — "beach", "dog", "birthday cake" via a local OpenCLIP model.
- **Albums & favorites**, **map view** (GPS EXIF, Leaflet), **lightbox viewer**
  with per-face tagging.
- Everything stays on your machine. Original photo files are **never modified**;
  all tags live in `data/photos.db` (SQLite).

## Run

```
run.bat
```

First run creates a virtualenv, installs dependencies, and downloads the AI models
(~650 MB total, one time). Then open http://localhost:8000, go to **Settings**,
add your photo folder(s), and click **Scan**.

## Requirements

- Windows, Python 3.12 (run.bat expects `%LOCALAPPDATA%\Programs\Python\Python312`)
- No GPU needed (CPU inference; ~1-2 s per photo)
