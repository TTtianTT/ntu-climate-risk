#!/usr/bin/env python3
"""Independent checks on actual cached inputs and exported outputs."""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, record, save_json, sha256


def main():
    manifest = json.loads((ROOT / "data/metadata/source_manifest.json").read_text())
    for entry in manifest:
        file = ROOT / entry["local_path"]
        assert file.exists(), f"Missing manifest file: {file}"
        assert sha256(file) == entry["sha256"], f"Hash mismatch: {file}"
    assert not any(e["data_kind"] == "synthetic" for e in manifest)
    obs = pd.read_parquet(ROOT / "data/processed/observations.parquet")
    daily = pd.read_csv(ROOT / "data/processed/daily_quality.csv")
    meta = json.loads((ROOT / "data/processed/summary.json").read_text())
    assert len(meta["days"]) == 30
    assert obs.station_id.eq("S44").all()
    assert set(obs.variable) == {"temperature", "humidity", "rainfall", "wind_speed"}
    assert all(s["id"] == "S44" and s["name"] == "Nanyang Avenue" for s in meta["station_metadata"].values())
    assert obs.timestamp_raw.str.endswith("+08:00").all()
    assert len(obs) == len(obs.drop_duplicates(["source", "station_id", "variable", "timestamp"]))
    assert daily[daily.variable == "rainfall"].coverage.min() > 0.8
    assert daily.groupby("variable").size().eq(30).all()
    layers = dict(pyogrio.list_layers(ROOT / "data/processed/campus.gpkg"))
    assert {"campus", "buildings", "walks", "pois", "grid", "stations"}.issubset(layers)
    grid = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="grid")
    assert grid.crs.to_epsg() == 3414 and grid.is_valid.all()
    assert grid.covered_unknown_m.sum() > 0 and grid.covered_no_m.sum() >= 0
    grid_web = gpd.read_file(ROOT / "data/processed/grid.geojson")
    assert grid_web.crs.to_epsg() == 4326
    lon, lat = grid_web.geometry.iloc[0].representative_point().coords[0]
    assert 103 < lon < 104 and 1 < lat < 2
    table = pd.read_csv(ROOT / "outputs/tables/grid_scenarios.csv")
    analysis = json.loads((ROOT / "outputs/tables/analysis_summary.json").read_text())
    assert table.groupby("scenario").grid_id.nunique().eq(len(grid)).all()
    assert table.proxy_degC_h_m.notna().all()
    assert abs(analysis["common_color_max"] - table.proxy_degC_h_m.max()) < 1e-6
    base = table[table.scenario == "Observed-sample baseline"].set_index("grid_id")
    shelter = table[table.scenario == "Shelter 50%"].set_index("grid_id")
    selected = set(analysis["selected_grid_ids"])
    assert (shelter.loc[list(selected), "proxy_degC_h_m"] <= base.loc[list(selected), "proxy_degC_h_m"]).all()
    other = list(set(base.index) - selected)
    assert (shelter.loc[other, "proxy_degC_h_m"] == base.loc[other, "proxy_degC_h_m"]).all()
    result = {"status": "passed", "sample_period": [min(meta["days"]), max(meta["days"])],
              "station_id": "S44", "rows_by_variable": obs.groupby("variable").size().to_dict(),
              "suspect_rows_by_variable": obs.groupby("variable").suspect.sum().astype(int).to_dict(),
              "coverage_by_variable": daily.groupby("variable").coverage.agg(["min", "mean", "max"]).to_dict("index"),
              "spatial_counts": meta["spatial_counts"],
              "campus_building_count": int(gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="buildings").inside_campus_osm.sum()),
              "campus_walk_way_count": int(gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="walks").inside_campus_osm.sum()),
              "covered_unknown_fraction_of_walk_length": float(grid.covered_unknown_m.sum() / grid.walk_m.sum()),
              "manifest_entries_checked": sum(e["local_path"] != "outputs/tables/real_data_validation.json" for e in manifest),
              "baseline_H_degC_h": analysis["heat"]["0.0"]["heat_degree_hours"]}
    validation_path = ROOT / "outputs/tables/real_data_validation.json"
    save_json(validation_path, result)
    validation_entry = record(validation_path, url="local validation", provider="NTU climate-risk prototype",
                              params={"checked_manifest_entries_before_write": len(manifest)}, kind="derived",
                              variable="real data end-to-end validation", unit="checks and counts",
                              time_range=f"{min(meta['days'])} to {max(meta['days'])}",
                              notes="Software/data integrity checks; not scientific model validation")
    refreshed = {e["local_path"]: e for e in manifest}
    refreshed[validation_entry["local_path"]] = validation_entry
    save_json(ROOT / "data/metadata/source_manifest.json", list(refreshed.values()))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
