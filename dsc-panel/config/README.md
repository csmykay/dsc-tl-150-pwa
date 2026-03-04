# Config directory

This directory is mounted into the container at `/app/config`. It persists across container rebuilds.

- **`.env`** — Copy from `.env.example`, then set `DSC_HOST`, `DSC_USER`, `DSC_PASS`, and `DSC_PIN`. After editing, run `docker compose restart` (no rebuild needed).
- **`zone_names.json`** — Created automatically on first run. Edit zone labels in the app UI, or edit this file directly.
