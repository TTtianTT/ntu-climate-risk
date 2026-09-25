#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, date_range, save_json
from ntu_climate.spatial import make_grid, parse_osm, save_spatial
from ntu_climate.weather import aggregate_quality, daily_quality, load_weather


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--station", default="S44")
    p.add_argument("--grid-size", type=int, default=100)
    p.add_argument("--minimum-coverage", type=float, default=0.8)
    p.add_argument("--start", help="Inclusive local day; overrides latest fetch selection")
    p.add_argument("--end", help="Inclusive local day; overrides latest fetch selection")
    args = p.parse_args()
    if args.start or args.end:
        if not (args.start and args.end):
            p.error("--start and --end must be supplied together")
        expected_days = date_range(1, args.start, args.end)
    else:
        status_file = ROOT / "data/metadata/fetch_status.json"
        if not status_file.exists():
            raise SystemExit("No fetch selection found. Run fetch_data.py first, or pass --start and --end.")
        expected_days = json.loads(status_file.read_text())["requested_days"]
    observations, _, stations = load_weather(args.station, expected_days)
    if observations.empty:
        raise SystemExit("No cached real observations. Run fetch_data.py first.")
    for variable in ("temperature", "rainfall", "humidity", "wind_speed"):
        missing = [day for day in expected_days if not (ROOT / "data/raw/weather" / variable / f"{day}.json").exists()]
        if missing:
            raise SystemExit(f"Missing cached {variable} days: {missing}. No synthetic fallback.")
    hourly = aggregate_quality(observations, args.minimum_coverage, expected_days)
    daily = daily_quality(hourly, args.minimum_coverage)
    output = ROOT / "data/processed"
    output.mkdir(parents=True, exist_ok=True)
    observations.to_parquet(output / "observations.parquet", index=False)
    hourly.to_csv(output / "hourly_quality.csv", index=False)
    daily.to_csv(output / "daily_quality.csv", index=False)
    save_json(output / "stations.json", stations)
    layers = parse_osm()
    grid = make_grid(layers["campus"], layers["walks"], args.grid_size)
    counts = save_spatial(layers, grid, stations.get("temperature"))
    save_json(output / "summary.json", {"station_id": args.station, "station_metadata": stations,
                                        "spatial_counts": counts, "observation_rows": len(observations),
                                        "days": expected_days,
                                        "grid_size_m": args.grid_size, "minimum_coverage": args.minimum_coverage})
    print(json.dumps({"spatial_counts": counts, "observations": len(observations), "days": len(observations["local_day"].unique())}, indent=2))


if __name__ == "__main__":
    main()
