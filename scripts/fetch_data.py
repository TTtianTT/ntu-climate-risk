#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, Downloader, date_range, fetch_daily, fetch_osm, fetch_v2_probe, fetch_v2_latest, save_json


def main():
    p = argparse.ArgumentParser(description="Fetch cached, real OSM and NEA observations")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--skip-osm", action="store_true")
    p.add_argument("--skip-v2-probe", action="store_true")
    args = p.parse_args()
    days = date_range(args.days, args.start, args.end)
    downloader = Downloader()
    entries = []
    errors = []
    if not args.skip_osm:
        try:
            entries.append(fetch_osm(args.offline, downloader))
            print("OSM cached")
        except Exception as exc:
            errors.append(f"OSM: {type(exc).__name__}: {exc}")
    if not args.offline and not args.skip_v2_probe:
        for variable in ("temperature", "rainfall", "humidity", "wind_speed"):
            try:
                entries.append(fetch_v2_latest(variable, downloader))
                entries.extend(fetch_v2_probe(variable, days[-1], downloader))
            except Exception as exc:
                errors.append(f"v2 probe {variable}: {type(exc).__name__}: {exc}")
    for day in days:
        try:
            day_entries = fetch_daily([day], args.offline, downloader=downloader)
            entries.extend(day_entries)
            print(f"{day}: {len(day_entries)} daily variables cached", flush=True)
        except Exception as exc:
            errors.append(f"{day}: {type(exc).__name__}: {exc}")
            print(errors[-1], file=sys.stderr, flush=True)
    # Preserve already cached probe provenance when extending 7 days to 30 days.
    existing_path = ROOT / "data/metadata/source_manifest.json"
    if existing_path.exists():
        previous = json.loads(existing_path.read_text())
        by_path = {entry["local_path"]: entry for entry in previous}
        by_path.update({entry["local_path"]: entry for entry in entries})
        entries = list(by_path.values())
    save_json(existing_path, entries)
    save_json(ROOT / "data/metadata/fetch_status.json", {"requested_days": days, "errors": errors,
                                                        "cached_daily_entries": sum("/weather/" in x["local_path"] and "v2_probe" not in x["local_path"] for x in entries)})
    print(f"Manifest: {len(entries)} entries; errors: {len(errors)}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
