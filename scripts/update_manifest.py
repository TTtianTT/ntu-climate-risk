#!/usr/bin/env python3
"""Register derived outputs and assumptions alongside observed raw sources."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, record, save_json, sha256


def main():
    path = ROOT / "data/metadata/source_manifest.json"
    prior = json.loads(path.read_text())
    observed = [e for e in prior if e["data_kind"] == "observed"]
    raw_hashes = {e["local_path"]: e["sha256"] for e in observed if "v2_probe" not in e["local_path"]}
    config = ROOT / "configs/default.yaml"
    links = {"observed_source_sha256": raw_hashes, "scenario_config_sha256": sha256(config)}
    entries = list(observed)
    files = [*sorted((ROOT / "data/processed").glob("*")),
             *sorted((ROOT / "outputs/figures").glob("*")),
             *sorted((ROOT / "outputs/tables").glob("*")),
             *sorted((ROOT / "outputs/maps").glob("*"))]
    for file in files:
        if not file.is_file():
            continue
        entries.append(record(file, url="local calculation", provider="NTU climate-risk prototype",
                              params=links, kind="derived", station_id="S44" if "weather" in file.name or "scenario" in file.name else None,
                              variable=file.stem, unit="see file columns, figure legend, or METHODS.md",
                              time_range="see processed/summary.json", notes="Derived from cached observed inputs and explicit config; not direct measurement",
                              terms="https://www.openstreetmap.org/copyright"))
    entries.append(record(config, url="local configuration", provider="NTU climate-risk prototype",
                          params={}, kind="assumed", variable="screening parameters and sensitivity scenarios",
                          unit="mixed; see YAML keys", notes="Self-selected assumptions, not official future projections",
                          terms="https://ccrs.weather.gov.sg/climate-projections/"))
    save_json(path, entries)
    print(f"Manifest entries: {len(entries)} ({len(observed)} observed, {len(entries)-len(observed)-1} derived, 1 assumed)")


if __name__ == "__main__":
    main()
