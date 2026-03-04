"""FastAPI app — routes, SSE, lifespan."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from scraper import PanelStatus, TL150Scraper

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/app/config")
ZONE_NAMES_FILE = os.path.join(CONFIG_DIR, "zone_names.json")


def _parse_zone_spec(spec: str) -> list[int]:
    """Parse ZONE_LIMIT: whole number (8/16/32) or comma-separated list of N or N-M. Returns sorted unique zone numbers 1..32."""
    spec = spec.strip()
    if not spec:
        return list(range(1, 17))
    # Single whole number (legacy): 8, 16, or 32
    try:
        v = int(spec)
        if v in (8, 16, 32):
            return list(range(1, v + 1))
    except ValueError:
        pass
    # Comma-separated: "1-8,10,12,14" or "1-4,8,10,30-32"
    result: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                lo, hi = int(a.strip()), int(b.strip())
                if 1 <= lo <= hi <= 32:
                    result.extend(range(lo, hi + 1))
            except ValueError:
                continue
        else:
            try:
                n = int(part)
                if 1 <= n <= 32:
                    result.append(n)
            except ValueError:
                continue
    # Sorted, unique, preserve order of first occurrence
    seen: set[int] = set()
    out: list[int] = []
    for n in sorted(result):
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out if out else list(range(1, 17))


def _zone_numbers() -> list[int]:
    return _parse_zone_spec(os.environ.get("ZONE_LIMIT", "16").strip())


def _zone_limit() -> int:
    return len(_zone_numbers())


def _app_title() -> str:
    return os.environ.get("APP_TITLE", "Home Security").strip() or "Home Security"


def _short_name() -> str:
    name = os.environ.get("APP_SHORT_NAME", "Home").strip() or "Home"
    # Ensure space after apostrophe-s (e.g. "Smykay'sHouse" -> "Smykay's House")
    name = re.sub(r"'s([A-Z])", r"'s \1", name)
    return name


current_status: Optional[PanelStatus] = None
sse_queues: list[asyncio.Queue] = []
poll_task: Optional[asyncio.Task] = None


def _default_zone_names(limit: int | None = None) -> dict[str, str]:
    limit = limit or _zone_limit()
    return {str(i): f"Zone {i}" for i in range(1, limit + 1)}


def _default_zone_names_from_list(zone_nums: list[int]) -> dict[str, str]:
    return {str(i): f"Zone {i}" for i in zone_nums}


def load_zone_names() -> dict[str, str]:
    zone_nums = _zone_numbers()
    path = Path(ZONE_NAMES_FILE)
    if not path.is_file():
        return _default_zone_names_from_list(zone_nums)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_zone_names_from_list(zone_nums)
        out = {}
        for k, v in data.items():
            try:
                if int(k) in zone_nums:
                    out[str(k)] = str(v)
            except (TypeError, ValueError):
                pass
        return out
    except Exception:
        return _default_zone_names_from_list(zone_nums)


def save_zone_names(names: dict[str, str]) -> None:
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(ZONE_NAMES_FILE)
    with open(path, "w") as f:
        json.dump(names, f, indent=2)


def status_to_dict(s: Optional[PanelStatus]) -> dict:
    if s is None:
        raise HTTPException(status_code=503, detail="Status not yet available")
    zone_nums = _zone_numbers()
    zone_names = load_zone_names()
    zone_by_num = {z.number: z for z in s.zones}
    zones_payload = []
    for num in zone_nums:
        z = zone_by_num.get(num)
        name = zone_names.get(str(num), f"Zone {num}")
        zones_payload.append({
            "number": num,
            "name": name,
            "state": z.state if z else "closed",
            "last_activity": z.last_activity if z else "",
        })
    return {
        "armed": s.armed,
        "arm_mode": s.arm_mode,
        "ready": s.ready,
        "trouble": s.trouble,
        "raw_system_color": s.raw_system_color,
        "app_title": _app_title(),
        "zone_limit": len(zone_nums),
        "zone_numbers": zone_nums,
        "zones": zones_payload,
    }


async def poll_loop(scraper: TL150Scraper) -> None:
    global current_status
    poll_secs = int(os.environ.get("POLL_SECS", "10"))
    while True:
        try:
            current_status = await scraper.fetch_status()
            payload = json.dumps(status_to_dict(current_status))
            dead = []
            for q in sse_queues:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                sse_queues.remove(q)
        except Exception as e:
            log.exception("TL-150 poll failed: %s", e)
        await asyncio.sleep(poll_secs)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    if not Path(ZONE_NAMES_FILE).is_file():
        save_zone_names(_default_zone_names_from_list(_zone_numbers()))
    scraper = TL150Scraper()
    poll_task = asyncio.create_task(poll_loop(scraper))
    yield
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
    await scraper.close()


app = FastAPI(lifespan=lifespan)


@app.get("/api/status")
async def get_status():
    if current_status is None:
        raise HTTPException(status_code=503, detail="Status not yet available")
    return status_to_dict(current_status)


@app.post("/api/arm/away")
async def arm_away():
    scraper = TL150Scraper()
    try:
        await scraper.arm_away()
        await asyncio.sleep(1.5)
        global current_status
        current_status = await scraper.fetch_status()
        payload = json.dumps(status_to_dict(current_status))
        for q in list(sse_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        return {"ok": True, "action": "arm_away"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await scraper.close()


@app.post("/api/arm/stay")
async def arm_stay():
    scraper = TL150Scraper()
    try:
        await scraper.arm_stay()
        await asyncio.sleep(1.5)
        global current_status
        current_status = await scraper.fetch_status()
        payload = json.dumps(status_to_dict(current_status))
        for q in list(sse_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        return {"ok": True, "action": "arm_stay"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await scraper.close()


@app.post("/api/disarm")
async def disarm():
    scraper = TL150Scraper()
    try:
        await scraper.disarm()
        await asyncio.sleep(1.5)
        global current_status
        current_status = await scraper.fetch_status()
        payload = json.dumps(status_to_dict(current_status))
        for q in list(sse_queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        return {"ok": True, "action": "disarm"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        await scraper.close()


@app.get("/api/config")
async def get_config():
    zn = _zone_numbers()
    return {"app_title": _app_title(), "short_name": _short_name(), "zone_limit": len(zn), "zone_numbers": zn}


@app.get("/api/zone-names")
async def get_zone_names():
    return load_zone_names()


@app.put("/api/zone-names")
async def put_zone_names(body: dict):
    zone_nums = _zone_numbers()
    names = {}
    for k, v in body.items():
        try:
            n = int(k)
            if n in zone_nums:
                names[str(n)] = str(v) if v else f"Zone {n}"
        except (TypeError, ValueError):
            continue
    for i in zone_nums:
        if str(i) not in names:
            names[str(i)] = f"Zone {i}"
    save_zone_names(names)
    return {"ok": True}


@app.get("/api/events")
async def sse_events():
    from fastapi.responses import StreamingResponse

    async def stream():
        queue: asyncio.Queue = asyncio.Queue()
        sse_queues.append(queue)
        try:
            if current_status is not None:
                yield f"data: {json.dumps(status_to_dict(current_status))}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in sse_queues:
                sse_queues.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# PWA manifest (name/short_name from env; icons served from config/icons at /icons/)
PWA_ICONS = [
    {"src": "/icons/icon-16x16.png", "sizes": "16x16", "type": "image/png"},
    {"src": "/icons/icon-32x32.png", "sizes": "32x32", "type": "image/png"},
    {"src": "/icons/icon-48x48.png", "sizes": "48x48", "type": "image/png"},
    {"src": "/icons/icon-64x64.png", "sizes": "64x64", "type": "image/png"},
    {"src": "/icons/icon-96x96.png", "sizes": "96x96", "type": "image/png"},
    {"src": "/icons/icon-128x128.png", "sizes": "128x128", "type": "image/png"},
    {"src": "/icons/icon-192x192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icons/icon-256x256.png", "sizes": "256x256", "type": "image/png"},
    {"src": "/icons/icon-384x384.png", "sizes": "384x384", "type": "image/png"},
    {"src": "/icons/icon-512x512.png", "sizes": "512x512", "type": "image/png"},
    {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
]


@app.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse(
        {
            "name": _app_title(),
            "short_name": _short_name(),
            "description": "Home monitoring and security system",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#ffffff",
            "theme_color": "#1a73e8",
            "icons": PWA_ICONS,
        },
        media_type="application/manifest+json",
    )


@app.get("/icons/{filename:path}")
async def serve_icon(filename: str):
    """Serve PWA icons from config/icons (host-mounted)."""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    icons_dir = Path(CONFIG_DIR) / "icons"
    filepath = (icons_dir / filename).resolve()
    try:
        filepath.relative_to(icons_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(filepath)


@app.get("/{path:path}")
async def serve_static(path: str):
    static_dir = "/app/static"
    if path == "" or path == "/":
        path = "index.html"
    filepath = os.path.join(static_dir, path)
    if os.path.isfile(filepath):
        return FileResponse(filepath)
    index_path = os.path.join(static_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not found")
