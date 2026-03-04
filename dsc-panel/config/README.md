# Config directory

This directory is mounted into the container at `/app/config`. It persists across container rebuilds.

- **`.env`** — Copy from `.env.example`, then set `DSC_HOST`, `DSC_USER`, `DSC_PASS`, and `DSC_PIN`. Optional: `APP_TITLE`, `APP_SHORT_NAME` (PWA name/short name). After editing, run `docker compose restart` (no rebuild needed).
- **`zone_names.json`** — Created automatically on first run. Edit zone labels in the app UI, or edit this file directly.
- **`icons/`** — PWA icons (e.g. `icon-16x16.png` … `icon-512x512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`). Served at `/icons/` and used by the web app manifest.
