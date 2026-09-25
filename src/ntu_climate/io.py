"""HTTP download, cache, and source records. No synthetic fallback."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
SGT = ZoneInfo("Asia/Singapore")
VARIABLES = {"temperature": "air-temperature", "rainfall": "rainfall", "humidity": "relative-humidity", "wind_speed": "wind-speed"}
V1 = "https://api.data.gov.sg/v1/environment"
V2 = "https://api-open.data.gov.sg/v2/real-time/api"
OSM_URL = "https://api.openstreetmap.org/api/0.6/map"
OSM_BBOX = "103.670,1.335,103.695,1.365"
OGL = "https://data.gov.sg/open-data-licence"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def record(path: Path, *, url: str, provider: str, params: dict, kind: str,
           station_id: str | None = None, variable: str | None = None,
           unit: str | None = None, time_range: str | None = None,
           row_count: int | None = None, notes: str = "", terms: str | None = None) -> dict:
    # Cache reads and manifest refreshes must not masquerade as a new download.
    # The saved file's modification time records when these immutable raw/cache files were written.
    return dict(source_url=url, provider=provider,
                retrieved_at=datetime.fromtimestamp(path.stat().st_mtime, SGT).isoformat(),
                query_parameters=params, license_or_terms_url=terms or OGL,
                local_path=str(path.relative_to(ROOT)), sha256=sha256(path), data_kind=kind,
                station_id=station_id, variable=variable, unit=unit, time_range=time_range,
                row_count=row_count, quality_notes=notes)


class Downloader:
    def __init__(self, interval_s: float = 1.8):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "NTU-climate-risk-course-prototype/0.1 (OSM/NEA attribution)"})
        key = os.environ.get("DATA_GOV_SG_API_KEY")
        if key:
            self.session.headers["x-api-key"] = key
        self.interval_s = interval_s
        self.last_request = 0.0

    def get(self, url: str, params: dict | None = None) -> bytes:
        for attempt in range(4):
            delay = self.interval_s - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                self.last_request = time.monotonic()
                response = self.session.get(url, params=params, timeout=(10, 90))
                if response.status_code in (429, 500, 502, 503, 504):
                    retry = response.headers.get("Retry-After")
                    wait = min(float(retry), 90) if retry and retry.isdigit() else min(2 ** attempt * 2, 30)
                    if attempt < 3:
                        time.sleep(wait)
                        continue
                response.raise_for_status()
                return response.content
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(min(2 ** attempt * 2, 30))
        raise RuntimeError(f"Download failed after retries: {url}")


def date_range(days: int, start: str | None, end: str | None) -> list[str]:
    latest = datetime.now(SGT).date() - timedelta(days=1)
    end_date = datetime.fromisoformat(end).date() if end else latest
    if end_date > latest:
        raise ValueError("End must be a completed Asia/Singapore local day")
    start_date = datetime.fromisoformat(start).date() if start else end_date - timedelta(days=days - 1)
    if start_date > end_date:
        raise ValueError("start is after end")
    return [(start_date + timedelta(days=i)).isoformat() for i in range((end_date - start_date).days + 1)]


def _entry_for_daily(path: Path, variable: str, day: str) -> dict:
    body = json.loads(path.read_text())
    if not isinstance(body.get("items"), list) or not isinstance(body.get("metadata", {}).get("stations"), list):
        raise ValueError(f"Unexpected v1 response in {path}")
    meta = body["metadata"]
    return record(path, url=f"{V1}/{VARIABLES[variable]}", provider="NEA via data.gov.sg",
                  params={"date": day}, kind="observed", station_id="S44 (preferred; checked during processing)",
                  variable=variable, unit=meta.get("reading_unit"), time_range=day,
                  row_count=len(body["items"]), notes="All available stations in raw daily response; station-specific coverage checked downstream")


def fetch_daily(days: list[str], offline: bool = False, variables: list[str] | None = None,
                downloader: Downloader | None = None) -> list[dict]:
    downloader = downloader or Downloader()
    entries = []
    for day in days:
        for variable in variables or list(VARIABLES):
            path = ROOT / "data/raw/weather" / variable / f"{day}.json"
            if not path.exists():
                if offline:
                    raise FileNotFoundError(f"Missing cached observed data: {path}")
                raw = downloader.get(f"{V1}/{VARIABLES[variable]}", {"date": day})
                body = json.loads(raw)
                if not isinstance(body.get("items"), list) or not body["items"]:
                    raise ValueError(f"Empty or unexpected official response: {variable} {day}: {str(body)[:250]}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            entries.append(_entry_for_daily(path, variable, day))
    return entries


def fetch_osm(offline: bool = False, downloader: Downloader | None = None) -> dict:
    path = ROOT / "data/raw/osm/ntu_bbox.osm"
    if not path.exists():
        if offline:
            raise FileNotFoundError(f"Missing cached OSM data: {path}")
        raw = (downloader or Downloader()).get(OSM_URL, {"bbox": OSM_BBOX})
        if b"<osm" not in raw[:1000]:
            raise ValueError("OSM API did not return XML map data")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return record(path, url=OSM_URL, provider="OpenStreetMap contributors", params={"bbox": OSM_BBOX},
                  kind="observed", variable="OSM mapped features", unit="WGS84 degrees",
                  notes="Community mapped features; amenity=university boundary needs field/official verification",
                  terms="https://www.openstreetmap.org/copyright")


def fetch_v2_probe(variable: str, day: str, downloader: Downloader, max_pages: int = 2) -> list[dict]:
    """Save limited schema probes. Full daily observation uses v1; this is not coverage data."""
    token = None
    entries = []
    for page in range(1, max_pages + 1):
        params = {"date": day}
        if token:
            params["paginationToken"] = token
        path = ROOT / "data/raw/weather/v2_probe" / f"{variable}_{day}_p{page}.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(downloader.get(f"{V2}/{VARIABLES[variable]}", params))
        body = json.loads(path.read_text())
        if body.get("code") != 0 or not isinstance(body.get("data", {}).get("readings"), list):
            raise ValueError(f"Unexpected v2 response: {variable} {day} page {page}")
        data = body["data"]
        entries.append(record(path, url=f"{V2}/{VARIABLES[variable]}", provider="NEA via data.gov.sg",
                              params=params, kind="observed", variable=f"{variable} schema probe",
                              unit=data.get("readingUnit"), row_count=len(data["readings"]),
                              time_range=day, notes="Schema/pagination probe only; not used in analysis"))
        token = data.get("paginationToken")
        if not token:
            break
    return entries


def fetch_v2_all_pages(variable: str, day: str, downloader: Downloader) -> list[dict]:
    """Exhaust a v2 date query. Never use a partial page set for coverage analysis."""
    token = None
    seen = set()
    pages = []
    for _ in range(1000):
        params = {"date": day}
        if token:
            params["paginationToken"] = token
        body = json.loads(downloader.get(f"{V2}/{VARIABLES[variable]}", params))
        if body.get("code") != 0 or not isinstance(body.get("data", {}).get("readings"), list):
            raise ValueError("Invalid v2 page; refusing partial coverage")
        pages.append(body)
        token = body["data"].get("paginationToken")
        if not token:
            return pages
        if token in seen:
            raise ValueError("Repeated pagination token")
        seen.add(token)
    raise ValueError("Exceeded v2 pagination safety limit")


def fetch_v2_latest(variable: str, downloader: Downloader) -> dict:
    path = ROOT / "data/raw/weather/v2_probe" / f"{variable}_latest.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(downloader.get(f"{V2}/{VARIABLES[variable]}"))
    body = json.loads(path.read_text())
    if body.get("code") != 0 or not isinstance(body.get("data", {}).get("readings"), list):
        raise ValueError(f"Unexpected latest v2 response: {variable}")
    data = body["data"]
    return record(path, url=f"{V2}/{VARIABLES[variable]}", provider="NEA via data.gov.sg",
                  params={}, kind="observed", variable=f"{variable} latest schema probe",
                  unit=data.get("readingUnit"), row_count=len(data["readings"]),
                  time_range=data["readings"][0]["timestamp"] if data["readings"] else None,
                  notes="Latest-response metadata probe only; not used in historical analysis")
