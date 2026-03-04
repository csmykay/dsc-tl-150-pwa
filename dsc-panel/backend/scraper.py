"""TL-150 HTTP client and HTML parser."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


@dataclass
class Zone:
    number: int
    state: str  # "closed" | "open" | "recent"
    last_activity: str


@dataclass
class PanelStatus:
    armed: bool
    arm_mode: Optional[str]  # "away" | "stay" | None
    ready: bool
    trouble: bool
    zones: list[Zone]
    raw_system_color: str


class TL150Scraper:
    def __init__(self) -> None:
        self._base = f"http://{os.environ['DSC_HOST']}"
        self._auth = (
            os.environ.get("DSC_USER", "admin"),
            os.environ.get("DSC_PASS", ""),
        )
        self._pin = os.environ.get("DSC_PIN", "")
        self._client: Optional[httpx.AsyncClient] = None

    def _browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
            "Referer": f"{self._base}/2",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                auth=self._auth,
                timeout=15.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def fetch_status(self) -> PanelStatus:
        client = await self._get_client()
        r = await client.get(f"{self._base}/2")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        zones = self._parse_zones(soup)
        armed, arm_mode, ready, trouble, raw_color = self._parse_system(soup)
        return PanelStatus(
            armed=armed,
            arm_mode=arm_mode,
            ready=ready,
            trouble=trouble,
            zones=zones,
            raw_system_color=raw_color,
        )

    def _parse_zones(self, soup: BeautifulSoup) -> list[Zone]:
        zones: list[Zone] = []
        table = soup.find("table", class_="keypad")
        if not table:
            return zones
        cells = table.find_all("td")
        for i, td in enumerate(cells):
            zone_num = i + 1
            if zone_num > 64:
                break
            bg = (td.get("bgcolor") or "").strip().upper()
            span = td.find("span")
            title = (span.get("title") or "") if span else ""
            if "OPEN" in title.upper():
                state = "open"
            elif bg == "#B20000" or "B20000" in bg:
                state = "recent"
            elif bg == "#000000" or (not bg and "closed" in title.lower()):
                state = "closed"
            else:
                state = "open" if "OPEN" in title.upper() else "closed"
            zones.append(Zone(number=zone_num, state=state, last_activity=title or ""))
        return zones

    def _parse_system(self, soup: BeautifulSoup) -> tuple[bool, Optional[str], bool, bool, str]:
        armed = False
        arm_mode: Optional[str] = None
        ready = True
        trouble = False
        raw_color = "LIME"
        tables = soup.find_all("table", border=1)
        for table in tables:
            forms = table.find_all("form", action="2")
            for form in forms:
                a_input = form.find("input", {"name": "A"})
                if not a_input:
                    continue
                a_val = a_input.get("value")
                if a_val == "3":
                    armed = False
                    arm_mode = None
                elif a_val in ("1", "4"):
                    armed = True
                    arm_mode = "away" if a_val == "1" else "stay"
        for td in soup.find_all("td", bgcolor=True):
            bg = (td.get("bgcolor") or "").upper()
            text = (td.get_text() or "").strip().upper()
            if "LIME" in bg or "READY" in text:
                raw_color = "LIME"
                ready = True
            elif "YELLOW" in bg or "TROUBLE" in text:
                trouble = True
            elif "RED" in bg and "ARM" in text:
                armed = True
                raw_color = "RED"
        return armed, arm_mode, ready, trouble, raw_color

    async def arm_away(self) -> None:
        await self._send_command(3)

    async def arm_stay(self) -> None:
        await self._send_command(2)

    async def disarm(self) -> None:
        await self._send_command(4)  # TL-150 form uses A=4 for DISARM (A=1 is not disarm on this firmware)

    async def _send_command(self, a: int) -> None:
        client = await self._get_client()
        url = f"{self._base}/2"
        params = {"A": a, "p": 1, "X": self._pin}
        headers = self._browser_headers()
        # Some TL-150 firmware only runs the command if the request looks like a form
        # follow-up: load the page first (session/cookie), then send command with Referer.
        await client.get(url, headers=headers)
        r = await client.get(url, params=params, headers=headers)
        if r.status_code >= 400:
            log.warning("TL-150 command A=%s failed: status=%s body=%s", a, r.status_code, (r.text or "")[:300])
        r.raise_for_status()
