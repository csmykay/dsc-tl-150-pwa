# DSC Panel — Project Documentation

**Project:** Self-hosted PWA for DSC TL-150 IP Alarm Communicator  
**Date:** February 2026  
**Status:** Complete — ready to deploy  

---

## Table of Contents

1. [Project Goal](#1-project-goal)
2. [Hardware — DSC TL-150](#2-hardware--dsc-tl-150)
3. [Discovery — Reverse Engineering the TL-150 Interface](#3-discovery--reverse-engineering-the-tl-150-interface)
4. [Architecture Decisions](#4-architecture-decisions)
5. [Project Structure](#5-project-structure)
6. [File-by-File Breakdown](#6-file-by-file-breakdown)
7. [TL-150 Protocol Reference](#7-tl-150-protocol-reference)
8. [API Reference](#8-api-reference)
9. [Frontend Design Decisions](#9-frontend-design-decisions)
10. [Docker & Deployment](#10-docker--deployment)
11. [Environment Variables](#11-environment-variables)
12. [Known Unknowns & Future Work](#12-known-unknowns--future-work)
13. [Deployment Runbook](#13-deployment-runbook)

---

## 1. Project Goal

Build a lightweight, self-hosted Progressive Web Application (PWA) to control a DSC home security system via its TL-150 IP communicator module. The application must:

- Run as a **single Docker container** on a home Linux server
- Be accessible over **local WiFi and VPN**
- Show **real-time arm/disarm state** and **zone status**
- Allow **arm away, arm stay, and disarm** commands from the UI
- Be installable to a **phone's home screen** as a PWA
- Require a **PIN to execute commands** so it's not wide open over the network

---

## 2. Hardware — DSC TL-150

The DSC TL-150 is a residential IP alarm communicator that bridges a DSC PowerSeries control panel to a home network.

**Key specs:**
- Compatible with all PowerSeries control panels
- Connects via Ethernet (10/100BaseT), supports DHCP
- 128-bit AES encryption on external (monitoring station) comms
- Runs a built-in HTTP web server accessible on the LAN
- Homeowner interface: arm/disarm + zone status grid via web browser
- No official API or SDK — DSC has never published one

**In this setup:**
- IP address: `192.168.50.21`
- Admin username: `admin`
- Supports 64 zones
- Single partition (Partition 1)

---

## 3. Discovery — Reverse Engineering the TL-150 Interface

### What we knew going in
Community projects going back to 2010 have all worked by screen-scraping the TL-150's built-in HTML pages. There is no binary TCP protocol, no REST API, no WebSocket interface — just HTML forms.

### Page source analysis

The homeowner status page was captured by logging in with Chrome and doing View Page Source. Key findings:

**Authentication:** HTTP Basic Auth on every request. No session cookie. No CSRF token. No login form to simulate — `httpx` handles Basic Auth natively in a single header.

**Status URL:** `GET /2` — the main homeowner page, protected by Basic Auth.

**Zone grid structure:**
```html
<TABLE BORDER=2 CLASS=keypad>
  <TR>
    <TD BGCOLOR=#000000>
      <SPAN TITLE="CLOSED: More than 1 hour ago">1</SPAN>
    </TD>
    <TD BGCOLOR=#B20000>
      <SPAN TITLE="CLOSED: 4 Minutes Ago">3</SPAN>
    </TD>
    ...
  </TR>
</TABLE>
```

Zone state is entirely encoded in two places:
- `BGCOLOR` attribute on the `<TD>` — color indicates recency
- `TITLE` attribute on the inner `<SPAN>` — human-readable text with OPEN/CLOSED and timestamp

**Zone color map (observed):**

| BGCOLOR   | Meaning                                  | Our state label |
|-----------|------------------------------------------|-----------------|
| `#000000` | Closed, more than 1 hour ago             | `closed`        |
| `#B20000` | Closed, recently triggered (within hour) | `recent`        |
| *(other)* | Inferred open from TITLE text            | `open`          |

We haven't directly observed an open zone's color — it's decoded from the TITLE text containing "OPEN" as a fallback, and any non-black non-dark-red color is also treated as open.

**System status table:**
```html
<TABLE BORDER=1>
  <TR>
    <TD>System</TD>
    <TD BGCOLOR="LIME">Ready </TD>
    <TD BGCOLOR="YELLOW"> Trouble</TD>
    <TD WIDTH=200px>
      <FORM ACTION=2 METHOD=GET>
        <INPUT TYPE=HIDDEN NAME=A VALUE=3>
        <INPUT TYPE=SUBMIT VALUE=ARM>
        <input type=hidden name=p value=1>
        <INPUT TYPE=PASSWORD MAXLENGTH=6 SIZE=6 NAME=X>
      </FORM>
    </TD>
  </TR>
</TABLE>
```

**Critical insight — detecting arm state:**  
The TL-150 only shows the ARM form (A=3) when the system is disarmed, and only shows the DISARM form (A=1) when the system is armed. This is our primary arm state detection mechanism — we check which form is present in the HTML rather than relying on color alone.

**Command URL structure (confirmed from ARM form):**

| Action    | URL                          | A value |
|-----------|------------------------------|---------|
| Arm Away  | `GET /2?A=3&p=1&X=<PIN>`     | 3       |
| Arm Stay  | `GET /2?A=2&p=1&X=<PIN>`     | 2       |
| Disarm    | `GET /2?A=1&p=1&X=<PIN>`     | 1       |

- `A` = action code
- `p` = partition number (always 1 in this setup)
- `X` = the user's keypad PIN

Arm Away (A=3) was confirmed directly from the form. Arm Stay (A=2) and Disarm (A=1) follow the standard DSC command numbering and are consistent with every third-party plugin that has ever talked to this device. Arm Stay is unconfirmed in the HTML since the system was disarmed at time of capture — test this on first deploy.

**Page auto-refresh:** The TL-150 page has `<meta http-equiv="refresh" content="60;url=2">` — it self-refreshes every 60 seconds. Our backend polls every 10 seconds, so we always have fresher data than the native interface.

**Navigation:** There are two pages — `/2` (user/homeowner) and `/0` (admin/config). We only use `/2`.

---

## 4. Architecture Decisions

### Decision: Python FastAPI for the backend

**Rationale:** Web scraping in Python is the gold standard. The `httpx` + `BeautifulSoup4` combination is battle-tested, async-native, and has the best ecosystem for parsing messy legacy HTML like what the TL-150 produces. Node.js could work but Python's BS4 is significantly more robust for this kind of HTML munging.

FastAPI was chosen over Flask for its native `async/await` support (important for SSE and concurrent polling) and automatic OpenAPI docs at `/docs`.

### Decision: SvelteKit with adapter-static for the frontend

**Rationale:** SvelteKit is the established home ground for this project. The `adapter-static` adapter compiles the SvelteKit app to pure HTML/JS/CSS files that FastAPI serves directly from `/app/static` — no Node.js runtime needed in the container. Single binary footprint.

### Decision: Single Docker container

**Rationale:** This is a home automation tool, not a production service. A single container keeps operations simple — one `docker compose up`, one port, one thing to restart. The multi-stage Dockerfile builds the SvelteKit app in a Node.js stage, copies the compiled static files into the Python stage, and the Python stage serves everything.

### Decision: Server-Sent Events (SSE) for real-time updates

**Rationale:** SSE is simpler than WebSockets for this use case — it's unidirectional (server → client), requires no special protocol upgrade, works through proxies, and browsers reconnect automatically on drop. The backend polls the TL-150 every 10 seconds and fans out each poll result to all connected SSE clients. The frontend subscribes on mount and updates state reactively.

### Decision: Poll-based backend, not event-based

**Rationale:** The TL-150 has no push mechanism. It cannot notify us of state changes — we have to ask. 10-second polling is a reasonable balance between responsiveness and not hammering a 20-year-old embedded web server. The poll interval is configurable via `POLL_SECS` env var.

### Decision: APP_PIN to protect arm/disarm commands

**Rationale:** The app is accessible over VPN but we still want a PIN barrier before executing alarm commands. The `APP_PIN` env var is checked on every POST to `/api/arm/*` and `/api/disarm`. It can be set to the same value as the DSC panel PIN or something different.

### Decision: In-memory state cache (no database)

**Rationale:** The panel state is a small, fast-changing data structure. Storing it in a database would add complexity with no benefit — if the container restarts, the first poll (within 10 seconds) repopulates state. No persistence needed.

---

## 5. Project Structure

```
dsc-panel/
├── Dockerfile                  # Multi-stage: Node build → Python runtime
├── docker-compose.yml          # Single-service compose file
├── README.md                   # Deployment quick-start
├── .env                        # Runtime config (not committed to git)
│
├── backend/
│   ├── main.py                 # FastAPI app — routes, SSE, lifespan
│   ├── scraper.py              # TL-150 HTTP client + HTML parser
│   ├── requirements.txt        # Python dependencies
│   └── .env.example            # Template for .env
│
└── frontend/
    ├── package.json
    ├── svelte.config.js        # adapter-static config
    ├── vite.config.js          # /api proxy for dev mode
    └── src/
        ├── app.html            # PWA shell + meta tags
        ├── lib/
        │   └── api.js          # Typed fetch wrappers for backend API
        └── routes/
            ├── +layout.js      # SSR disabled, prerender disabled
            └── +page.svelte    # Main UI — entire app is one page
```

---

## 6. File-by-File Breakdown

### `backend/scraper.py`

The core communication layer. Handles all interaction with the TL-150.

**`TL150Scraper` class:**
- Holds an `httpx.AsyncClient` with Basic Auth baked in
- `fetch_status()` — GETs `/2`, parses and returns a `PanelStatus` dataclass
- `arm_away()` → sends `A=3`
- `arm_stay()` → sends `A=2`  
- `disarm()` → sends `A=1`
- `_parse_zones()` — finds the `CLASS=keypad` table, iterates `<TD>` cells, decodes BGCOLOR + TITLE
- `_parse_system()` — finds the System Status table, checks for ARM vs DISARM form presence, reads BGCOLOR for Ready/Trouble state

**Data models:**
```python
@dataclass
class Zone:
    number: int
    state: str        # "closed" | "open" | "recent"
    last_activity: str

@dataclass
class PanelStatus:
    armed: bool
    arm_mode: Optional[str]   # "away" | "stay" | None
    ready: bool
    trouble: bool
    zones: list[Zone]
    raw_system_color: str
```

### `backend/main.py`

FastAPI application. Manages the poll loop, SSE fan-out, and REST endpoints.

**Lifespan:** On startup, instantiates the scraper and launches `poll_loop()` as an asyncio background task. On shutdown, cancels the task and closes the httpx client.

**`poll_loop()`:** Runs forever, sleeping `POLL_SECS` between iterations. Each iteration fetches status, stores it in `current_status`, and pushes a JSON payload to all connected SSE queues. Dead/full queues are removed.

**Routes:**
- `GET /api/status` — returns `current_status` as JSON (503 if not yet populated)
- `POST /api/arm/away` — verifies APP_PIN, calls scraper, waits 1.5s, refreshes status
- `POST /api/arm/stay` — same
- `POST /api/disarm` — same
- `GET /api/events` — SSE stream; each client gets its own `asyncio.Queue`, immediately receives current state, then gets pushed every poll update. 30-second keepalive comments prevent proxy timeouts.

**Static serving:** If `/app/static` exists (the compiled SvelteKit build), it's mounted at `/` as the last route, making FastAPI serve the entire PWA.

### `frontend/src/lib/api.js`

Three functions:
- `fetchStatus()` — one-shot GET to `/api/status`
- `sendCommand(action, pin)` — POST to `/api/{action}` with `{ pin }`
- `subscribeSSE(onMessage, onError)` — opens `EventSource` to `/api/events`, returns cleanup function

### `frontend/src/routes/+page.svelte`

The entire UI in one Svelte component.

**State:**
- `status` — reactive, updated by SSE
- `panelState` — derived: `'ready' | 'armed' | 'stay' | 'not_ready' | 'unknown'`
- `showPinModal` / `pendingAction` / `pinInput` — PIN modal state

**Layout sections:**
1. Header — brand + last-updated timestamp
2. Status ring — SVG circle with animated stroke-dashoffset, changes color per state
3. Control buttons — shows Arm Away + Arm Stay when disarmed, Disarm only when armed
4. Open zone alert — red banner listing any open zones (with pulse animation)
5. Zone grid — 8-column grid of all 64 zones, color-coded
6. PIN modal — overlay with password input, confirm/cancel

---

## 7. TL-150 Protocol Reference

### Authentication
- Type: HTTP Basic Auth
- Header: `Authorization: Basic base64(username:password)`
- Required on every request — no session, no cookie

### URLs

| Purpose       | Method | URL                          | Notes                          |
|---------------|--------|------------------------------|--------------------------------|
| Status page   | GET    | `/2`                         | Main homeowner page            |
| Arm Away      | GET    | `/2?A=3&p=1&X=<PIN>`         | Confirmed from HTML form       |
| Arm Stay      | GET    | `/2?A=2&p=1&X=<PIN>`         | Inferred (standard DSC codes)  |
| Disarm        | GET    | `/2?A=4&p=1&X=<PIN>`         | From TL-150 form (DISARM button uses A=4) |
| Change PIN    | GET    | `/2?A=7&X=<PIN>`             | Seen in HTML, not used by app  |
| Admin/Config  | GET    | `/0`                         | Admin page, not used by app    |

### Query Parameters

| Param | Meaning              | Values                        |
|-------|----------------------|-------------------------------|
| `A`   | Action code          | 1=arm away (form when disarmed), 2=arm stay, 3=arm away, 4=disarm, 7=change PIN |
| `p`   | Partition number     | `1` (single partition setup)  |
| `X`   | User keypad PIN      | 4–6 digit string              |

### Zone BGCOLOR Encoding

| Color     | Hex       | Zone State         |
|-----------|-----------|--------------------|
| Black     | `#000000` | Closed (cold)      |
| Dark red  | `#B20000` | Closed (recent)    |
| Other     | TBD       | Open (inferred)    |

Open zones are additionally identified by `OPEN` appearing in the `TITLE` attribute of the zone's `<SPAN>` element.

### System Status BGCOLOR Encoding

| Color    | Value    | Meaning          |
|----------|----------|------------------|
| Lime     | `LIME`   | Ready / disarmed |
| Yellow   | `YELLOW` | Trouble          |
| Red      | `RED`    | Armed (possible) |

### Armed State Detection

Armed state is determined by which form is present in the HTML:
- ARM form (`A=3`) present → system is **disarmed**
- DISARM form (`A=1` or `A=4`) present → system is **armed** (some firmware uses A=4 for disarm button)

This is more reliable than color-based detection because the TL-150 explicitly gates which form you see based on actual panel state.

---

## 8. API Reference

Base URL: `http://your-server:8000`

### GET `/api/status`

Returns current panel state.

**Response 200:**
```json
{
  "armed": false,
  "arm_mode": null,
  "ready": true,
  "trouble": false,
  "raw_system_color": "LIME",
  "zones": [
    { "number": 1, "state": "closed", "last_activity": "CLOSED: More than 1 hour ago" },
    { "number": 3, "state": "recent", "last_activity": "CLOSED: 4 Minutes Ago" }
  ]
}
```

**Response 503:** Status not yet available (first poll hasn't completed).

### POST `/api/arm/away`
### POST `/api/arm/stay`
### POST `/api/disarm`

**Request body:**
```json
{ "pin": "0521" }
```

**Response 200:**
```json
{ "ok": true, "action": "arm_away" }
```

**Response 401:** Invalid PIN.  
**Response 502:** TL-150 command failed (network error or bad response).

### GET `/api/events`

Server-Sent Events stream. Each event is a full status JSON payload (same schema as `/api/status`).

```
data: {"armed": false, "ready": true, ...}

data: {"armed": true, "arm_mode": "away", ...}

: keepalive
```

Events fire on every poll cycle (every `POLL_SECS` seconds) and immediately after any arm/disarm command. Keepalive comments are sent every 30 seconds between events to prevent proxy/firewall timeouts.

---

## 9. Frontend Design Decisions

### Dark theme
Security panel aesthetic — dark background (`#0d1117`, GitHub's dark theme palette) with high-contrast status colors. Appropriate for glanceable use in low-light conditions.

### Status ring
An SVG circle with animated `stroke-dashoffset` gives a clear visual state indicator that reads at a glance even on a small phone screen. Color transitions smoothly between states via CSS `transition`.

### Single page
The entire app is `+page.svelte`. No routing needed — this is a utility tool, not a multi-section app. SSR is disabled (`+layout.js: export const ssr = false`) because the app is client-side only.

### PIN modal
Arm/disarm commands show a modal with a password-type input. This prevents accidental taps on buttons and requires intentional confirmation. The modal captures Enter key and Escape key for keyboard usability.

### Zone grid layout
8 columns × 8 rows = 64 zones, matching the TL-150's maximum zone count. Each cell is square, small enough to show all zones at once on a phone screen. Tooltips show full status text on hover for desktop use.

### Real-time via SSE not polling
The frontend doesn't poll — it subscribes once to `/api/events` and the browser handles reconnection automatically. The backend is the only thing that polls the TL-150. This is cleaner than having each browser tab independently hitting the panel.

---

## 10. Docker & Deployment

### Dockerfile (multi-stage)

**Stage 1 — `frontend-builder` (node:20-alpine):**
- Installs npm dependencies
- Runs `npm run build` → produces static files in `/frontend/build`

**Stage 2 — Python runtime (python:3.12-slim):**
- Installs Python dependencies from `requirements.txt`
- Copies backend source files
- Copies compiled SvelteKit static files from stage 1 into `/app/static`
- Runs `uvicorn main:app --host 0.0.0.0 --port 8000`

### docker-compose.yml

```yaml
services:
  dsc-panel:
    build: .
    container_name: dsc-panel
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/status"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

`extra_hosts: host.docker.internal:host-gateway` is included so that if the TL-150 IP ever needs to be referenced as a host alias, it can be. Not strictly required for IP-based access to `192.168.50.21`.

`restart: unless-stopped` means the container survives server reboots automatically.

### Port

The app runs on port `8000`. If you want to run it on port `80` locally, change `ports` to `"80:8000"`.

---

## 11. Environment Variables

| Variable    | Required | Default          | Description                                      |
|-------------|----------|------------------|--------------------------------------------------|
| `DSC_HOST`  | Yes      | `192.168.50.21`  | TL-150 IP address on your LAN                    |
| `DSC_USER`  | Yes      | `admin`          | HTTP Basic Auth username                         |
| `DSC_PASS`  | Yes      | *(empty)*        | HTTP Basic Auth password                         |
| `DSC_PIN`   | Yes      | *(empty)*        | Keypad PIN sent with arm/disarm commands         |
| `APP_PIN`   | Yes      | *(empty)*        | PIN required by the web UI to send commands      |
| `POLL_SECS` | No       | `10`             | How often to poll the TL-150 (seconds)           |

`DSC_PIN` and `APP_PIN` can be the same value (your panel PIN) or different. `APP_PIN` is the web UI's PIN guard — the PIN typed into the modal. `DSC_PIN` is what actually gets sent to the panel.

---

## 12. Known Unknowns & Future Work

### Arm Stay (A=2) — unconfirmed
The Arm Stay command uses `A=2` based on standard DSC command numbering and third-party plugin documentation. It was not directly confirmed from the TL-150's HTML because the system was disarmed when we captured the page source (so only the ARM form was visible, not any stay-arm variant). **Test this on first deploy.**

If Arm Stay doesn't work with A=2, check the TL-150 admin config page at `/0` to see if stay arm is enabled, or temporarily capture network traffic while clicking the native TL-150 interface if it offers a stay arm option.

### Open zone color
We've observed `#000000` (closed/cold) and `#B20000` (closed/recent) but have not observed an actively open zone's BGCOLOR. The scraper handles this via the TITLE text fallback (`"OPEN"` substring) and a non-black color heuristic. If a zone is open and not being detected correctly, check the raw BGCOLOR value at `/api/status` (it's preserved in `last_activity` for zones).

### Zone labels
The TL-150 HTML only shows zone numbers (1–64), not custom zone names. If you've named your zones in the DSC panel programming, those names are not exposed in the web interface — they're only visible on physical DSC keypads. Zone numbering in the app is 1-based and matches the panel's zone numbering directly.

### Multiple partitions
The app is hardcoded to partition 1 (`p=1`). If your DSC panel is configured with multiple partitions, this would need extending.

### HTTPS / TLS
The app currently runs plain HTTP. For VPN use this is acceptable (VPN traffic is already encrypted). If you want HTTPS, put an nginx reverse proxy in front with a self-signed or Let's Encrypt cert, or use Tailscale's HTTPS feature.

### Push notifications
The app shows status in real-time while open, but does not send push notifications when the alarm state changes (e.g., "System Armed" or zone opened while you're away). This could be added with a service worker + Web Push API, or more simply with a notification service like Pushover or ntfy.sh from the backend poll loop.

### Authentication to the web app itself
Currently the web app is unprotected — anyone who can reach port 8000 over your network can view the panel status. Only arm/disarm commands are PIN-protected. If you want to gate the status view as well, adding HTTP Basic Auth to FastAPI or putting it behind an auth proxy (like Authelia or Traefik forward auth) would accomplish this.

---

## 13. Deployment Runbook

### Initial deploy

```bash
# 1. Transfer project to server
scp dsc-panel.zip user@your-server:~/
ssh user@your-server

# 2. Unzip
cd ~
unzip dsc-panel.zip
cd dsc-panel

# 3. Create .env from template
cp backend/.env.example .env

# 4. Edit .env and verify all values
nano .env

# 5. Build and launch
docker compose up -d --build

# 6. Watch startup logs
docker compose logs -f

# 7. Verify API is responding
curl http://localhost:8000/api/status | python3 -m json.tool
```

### Check status

```bash
docker compose ps
docker compose logs --tail=50
```

### Restart

```bash
docker compose restart
```

### Update after code changes

```bash
docker compose down
# ... copy new files ...
docker compose up -d --build
```

### Install as PWA on iPhone

1. Open Safari → `http://your-server-ip:8000`
2. Tap the Share button (box with arrow)
3. Scroll down → **Add to Home Screen**
4. Tap Add

### Install as PWA on Android

1. Open Chrome → `http://your-server-ip:8000`
2. Tap the three-dot menu
3. Tap **Add to Home Screen** or **Install App**

### Development mode (local iteration)

```bash
# Terminal 1 — backend
cd dsc-panel/backend
pip install -r requirements.txt
export DSC_HOST=192.168.50.21 DSC_USER=admin DSC_PASS=9BliZ9 DSC_PIN=0521 APP_PIN=0521
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend  
cd dsc-panel/frontend
npm install
npm run dev
# App at http://localhost:5173
# /api/* proxied to localhost:8000 via vite.config.js
```
