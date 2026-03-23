# Config directory

This directory is mounted into the container at `/app/config`. It persists across container rebuilds.

**Where settings actually come from (runtime)**

| What you might think | What the app does |
|----------------------|-------------------|
| `settings.txt.example` in the repo | **Not read at run time.** Copy it to **`settings.txt`** on the host (same folder you mount to `/app/config`). |
| A Docker **named volume** on `/app/config` | Starts **empty** unless you copy files in. Empty ⇒ no `settings.txt` ⇒ **defaults** (title “Home Security”, 16 zones, 2 columns, …). |
| **Bind mount** e.g. `~/docker-data/dsc-panel/config:/app/config` | Whatever is in that host folder is what the app uses. Put **`settings.txt`**, **`.env`**, and optional **`zone_names.json`** there. |

The container path is always **`/app/config/settings.txt`** (override with env `CONFIG_DIR` only if you know what you’re doing). After `docker compose logs`, look for `Config: CONFIG_DIR=... settings.txt exists=... app_title=...` to confirm the app sees your file.

**How config is split**

| File | Purpose |
|------|---------|
| **`settings.txt`** | **App logic** — how the app runs: `zone_list`, `zone_columns`, titles, poll interval, arming countdown UI, default arm mode, etc. |
| **`.env`** | **Security / secrets** — TL-150 access only: `DSC_HOST`, `DSC_USER`, `DSC_PASS`, `DSC_PIN` (what talks to the panel and proves who you are). |
| **`zone_names.json`** | **Custom zone naming** — friendly labels per zone number (`"1": "Front door"`). Does not control which zones exist or layout; that comes from `settings.txt`. Copy from `zone_names.json.example` if you want a full template. |

- **`.env`** — Copy from `.env.example`. **TL-150 credentials:** `DSC_HOST`, `DSC_USER`, `DSC_PASS`, `DSC_PIN`. **`settings.txt` is the source of truth** for `zone_list`, `zone_columns`, etc. Optional `DSC_ZONE_LIST` / `DSC_ZONE_COLUMNS` are used **only when the app creates `settings.txt` for the first time** (no file yet); they are **not** read after that — remove them from `.env` if you already maintain `settings.txt`. After editing `.env` or `settings.txt`, `docker compose restart`.

- **Debug (optional):** `GET /api/debug/settings` — JSON showing `settings_file` path, `zone_columns` raw/effective, and `zone_numbers` from `zone_list`. Remove or block if exposed to the public internet.

- **`settings.txt`** — Copy from `settings.txt.example`. Prefer valid JSON; the server also accepts a **trailing comma** after the last property (common hand-edit mistake — previously that made the file fail and fall back to defaults).

- **`settings.txt` fields** — **App / runtime options only:** `zone_list` (which zone numbers exist on your panel, e.g. `"16"` or `"1-6,10"`), `app_title`, `app_short_name` (PWA), `poll_secs`, `arming_countdown_secs`, `zone_columns`, `default_arm_mode`. **No zone labels here** — those are only in `zone_names.json`. Restart after hand-editing.

- **`zone_names.json`** — **Zone name labels only** (`{"1": "Front door", ...}`). Copy from `zone_names.json.example` for a full 1–32 template. Which zones exist and how the grid is laid out come from **`settings.txt`** (`zone_list`, `zone_columns`). Missing keys use default `Zone N`. On upgrade, a legacy `zone_names` key inside `settings.txt` may be copied here once, then removed from `settings.txt`.

- **`icons/`** — PWA icons (e.g. `icon-16x16.png` … `icon-512x512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`). Served at `/icons/` and used by the web app manifest.
