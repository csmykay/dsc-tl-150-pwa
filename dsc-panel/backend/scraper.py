"""TL-150 HTTP client and HTML parser."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# TL-150 zone cell BGCOLOR values (firmware-specific; check these before title heuristics)
_ZONE_BG_CLOSED = "000000"  # closed
_ZONE_BG_OPEN = "EA3323"  # open
_ZONE_BG_OPEN_RECENT = "A22015"  # opened in last hour
_ZONE_BG_CLOSED_RECENT_LEGACY = "B20000"  # closed / recent activity (older captures)


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

    def _normalize_bgcolor(self, bgcolor: str | None) -> str:
        """Return hex digits only (e.g. 000000, B20000) for comparison."""
        if not bgcolor:
            return ""
        return "".join(c for c in bgcolor.strip().upper() if c in "0123456789ABCDEF")

    def _zone_number_from_cell(self, td, cell_index: int) -> int:
        """TL-150 puts the zone number in the cell text (see PROJECT_GOAL sample). Prefer that over cell order."""
        span = td.find("span")
        for node in (span, td):
            if node is None:
                continue
            text = node.get_text(strip=True)
            if text.isdigit():
                n = int(text)
                if 1 <= n <= 64:
                    return n
        return cell_index + 1

    def _zone_title_from_cell(self, td) -> str:
        """Tooltip may be on the inner SPAN or on the TD."""
        span = td.find("span")
        if span and span.get("title"):
            return str(span.get("title")).strip()
        if td.get("title"):
            return str(td.get("title")).strip()
        return ""

    def _closed_more_than_one_hour_from_title(self, title: str) -> bool:
        """TL-150 titles like CLOSED: More than 1 hour ago, or 60+ minutes / 1+ hours ago."""
        t = (title or "").upper()
        if "MORE THAN 1 HOUR" in t or "MORE THAN 1 HR" in t:
            return True
        m = re.search(r"(\d+)\s*HOURS?\s*AGO", t)
        if m and int(m.group(1)) >= 1:
            return True
        m = re.search(r"(\d+)\s*MINUTES?\s*AGO", t)
        if m and int(m.group(1)) >= 60:
            return True
        return False

    def _closed_within_one_hour_from_title(self, title: str) -> bool:
        """True if CLOSED tooltip indicates activity within the last hour (orange 'recent' dot)."""
        t = (title or "").upper()
        if "CLOSED" not in t:
            return False
        if self._closed_more_than_one_hour_from_title(title):
            return False
        m = re.search(r"(\d+)\s*MINUTES?\s*AGO", t)
        if m:
            return int(m.group(1)) < 60
        if re.search(r"\d+\s*SECONDS?\s*AGO", t):
            return True
        m = re.search(r"(\d+)\s*HOURS?\s*AGO", t)
        if m:
            return int(m.group(1)) < 1
        return False

    def _classify_zone_state(self, bgcolor: str | None, title: str) -> str:
        """
        Zone state from BGCOLOR first (observed TL-150 firmware), then TITLE, then fallbacks.
        - #000000 = closed
        - #EA3323 = open
        - #A22015 = opened in last hour (treated as open for UI / open-zone alerts)
        - #B20000 = legacy / alternate: closed with recent activity
        """
        title_u = (title or "").upper()
        bg = self._normalize_bgcolor(bgcolor)

        if bg == _ZONE_BG_CLOSED:
            if self._closed_within_one_hour_from_title(title):
                return "recent"
            return "closed"
        if bg == _ZONE_BG_OPEN:
            return "open"
        if bg == _ZONE_BG_OPEN_RECENT:
            # Firmware: often "opened recently"; CLOSED + time → orange recent for full 1h window via title
            if "CLOSED" in title_u:
                if self._closed_more_than_one_hour_from_title(title):
                    return "closed"
                return "recent"
            return "open"
        if bg == _ZONE_BG_CLOSED_RECENT_LEGACY:
            if self._closed_more_than_one_hour_from_title(title):
                return "closed"
            return "recent"

        if "OPEN" in title_u:
            return "open"
        if "CLOSED" in title_u:
            if self._closed_within_one_hour_from_title(title):
                return "recent"
            return "closed"

        if not bg:
            return "closed"

        # Unknown bgcolor: treat as open (other firmware variants)
        return "open"

    def _parse_zones(self, soup: BeautifulSoup) -> list[Zone]:
        """Parse all zone cells from every CLASS=keypad table; zone # from cell text when present."""
        by_num: dict[int, Zone] = {}
        tables = soup.find_all("table", class_="keypad")
        if not tables:

            def _class_has_keypad(c) -> bool:
                if not c:
                    return False
                if isinstance(c, str):
                    return "keypad" in c.lower()
                return any("keypad" in str(x).lower() for x in c)

            table = soup.find("table", class_=_class_has_keypad)
            if table:
                tables = [table]

        cell_index = 0
        for table in tables:
            for td in table.find_all("td"):
                zone_num = self._zone_number_from_cell(td, cell_index)
                cell_index += 1
                if zone_num > 64:
                    continue
                title = self._zone_title_from_cell(td)
                bg = td.get("bgcolor") or ""
                state = self._classify_zone_state(bg, title)
                by_num[zone_num] = Zone(
                    number=zone_num,
                    state=state,
                    last_activity=title,
                )

        return [by_num[k] for k in sorted(by_num.keys())]

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
