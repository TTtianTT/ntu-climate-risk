"""Transparent sensitivity scenarios for heat and rainfall."""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd

from .io import ROOT, save_json
from .weather import heat_degree_hours


def percent_change(new: float, baseline: float) -> float | None:
    return (new / baseline - 1) * 100 if baseline and np.isfinite(baseline) else None


def scenario_grid(grid: gpd.GeoDataFrame, h: float | None, q_unknown: float,
                  selected_ids: set[str] | None = None, reduction: float = 0.0) -> gpd.GeoDataFrame:
    if not 0 <= q_unknown <= 1 or not 0 <= reduction <= 1:
        raise ValueError("q_unknown and reduction must be within [0, 1]")
    out = grid.copy()
    selected = out["grid_id"].isin(selected_ids or set())
    out["effective_uncovered_m"] = out["covered_no_m"] + q_unknown * out["covered_unknown_m"]
    out.loc[selected, "effective_uncovered_m"] *= 1 - reduction
    out["proxy_degC_h_m"] = np.nan if h is None else h * out["effective_uncovered_m"]
    out["selected_for_shelter"] = selected
    return out


def scenario_table(grid: gpd.GeoDataFrame, observations: pd.DataFrame, cfg: dict,
                   expected_days: list[str] | None = None) -> tuple[pd.DataFrame, dict, dict]:
    threshold = float(cfg["temperature_threshold_c"])
    q = float(cfg["q_unknown"])
    ids = set(cfg.get("shelter_grid_ids") or [])
    missing = ids - set(grid["grid_id"])
    if missing:
        raise ValueError(f"Unknown shelter grid IDs: {sorted(missing)}")
    expected_days = expected_days or json.loads((ROOT / "data/processed/summary.json").read_text())["days"]
    heat = {str(w): heat_degree_hours(observations, threshold, float(w), expected_days) for w in cfg["warming_c"]}
    min_coverage = float(cfg["minimum_coverage"])
    qualified = all(item["coverage"] >= min_coverage for item in heat.values())
    base_h = heat["0.0"]["heat_degree_hours"] if qualified else None
    cases = [("Observed-sample baseline", 0.0, 0.0), ("Warming +1°C", 1.0, 0.0),
             ("Warming +2°C", 2.0, 0.0), ("Shelter 25%", 0.0, 0.25),
             ("Shelter 50%", 0.0, 0.5), ("Warming +2°C + shelter 50%", 2.0, 0.5)]
    frames = []
    summary = {"threshold_c": threshold, "q_unknown": q, "minimum_coverage": min_coverage,
               "station_id": cfg["station_id"], "heat": heat, "qualified_for_proxy": qualified,
               "selected_grid_ids": sorted(ids), "scenarios": []}
    baseline_total = None
    for name, warming, reduction in cases:
        h = heat[str(warming)]["heat_degree_hours"] if qualified else None
        outcome = scenario_grid(grid, h, q, ids, reduction)
        outcome["scenario"] = name
        outcome["warming_c"] = warming
        outcome["shelter_reduction"] = reduction
        outcome["proxy_q0"] = np.nan if h is None else h * (outcome["covered_no_m"] * np.where(outcome["selected_for_shelter"], 1-reduction, 1))
        outcome["proxy_q1"] = np.nan if h is None else h * ((outcome["covered_no_m"] + outcome["covered_unknown_m"]) * np.where(outcome["selected_for_shelter"], 1-reduction, 1))
        total = float(outcome["proxy_degC_h_m"].sum()) if h is not None else None
        if baseline_total is None and name == "Observed-sample baseline":
            baseline_total = total
        summary["scenarios"].append({"name": name, "warming_c": warming, "shelter_reduction": reduction,
                                     "H_degC_h": h, "total_proxy_degC_h_m": total,
                                     "q0_total_proxy_degC_h_m": float(outcome["proxy_q0"].sum()) if h is not None else None,
                                     "q1_total_proxy_degC_h_m": float(outcome["proxy_q1"].sum()) if h is not None else None,
                                     "change_pct": percent_change(total, baseline_total) if total is not None else None})
        frames.append(pd.DataFrame(outcome.drop(columns="geometry")))
    table = pd.concat(frames, ignore_index=True)
    vmax = float(table["proxy_degC_h_m"].max()) if table["proxy_degC_h_m"].notna().any() else None
    summary["common_color_max"] = vmax
    rain = rainfall_events(observations, cfg.get("rainfall_multipliers", [1, 1.1, 1.2]), min_coverage,
                           float(cfg.get("rainfall_event_threshold_mm_h", 20.0)))
    return table, summary, rain


def rainfall_events(observations: pd.DataFrame, multipliers: list[float], minimum_coverage: float = 0.8,
                    threshold_mm_h: float = 20.0) -> dict:
    rain = observations[(observations["variable"] == "rainfall") & (~observations["suspect"])].copy()
    if rain.empty:
        return {"status": "unavailable", "reason": "No valid rainfall observations"}
    rain["hour_start"] = rain["interval_start"].dt.floor("h")
    hourly = rain.groupby("hour_start").agg(total_mm=("value", "sum"), valid_intervals=("value", "count")).reset_index()
    hourly["coverage"] = hourly["valid_intervals"] / 12
    hourly["status"] = np.where(hourly["coverage"] >= minimum_coverage, "qualified", "partial")
    qualified = hourly[hourly["status"] == "qualified"]
    maximum = qualified.loc[qualified["total_mm"].idxmax()] if not qualified.empty else None
    return {"status": "available" if maximum is not None else "partial-only",
            "strongest_qualified_hour_start": maximum["hour_start"].isoformat() if maximum is not None else None,
            "strongest_qualified_hour_mm": float(maximum["total_mm"]) if maximum is not None else None,
            "threshold_mm_h": threshold_mm_h, "qualified_hours": int(len(qualified)),
            "scenarios": [{"multiplier": float(m), "scaled_mm": float(maximum["total_mm"] * m) if maximum is not None else None}
                          | {"qualified_sample_hours_at_or_above_threshold": int((qualified["total_mm"] * m >= threshold_mm_h).sum())}
                          for m in multipliers],
            "meaning": "Sensitivity scaling of the same observed hours, without gap filling or changed event timing; threshold crossings may change"}


def export_analysis(table: pd.DataFrame, summary: dict, rain: dict, cfg: dict) -> None:
    tables = ROOT / "outputs/tables"
    tables.mkdir(parents=True, exist_ok=True)
    table.to_csv(tables / "grid_scenarios.csv", index=False)
    pd.DataFrame(summary["scenarios"]).to_csv(tables / "scenario_summary.csv", index=False)
    save_json(tables / "analysis_summary.json", {**summary, "rainfall": rain})
    save_json(tables / "scenario_config_used.json", cfg)
    # QGIS-ready scenario geometry is kept separate from immutable base spatial data.
    grid = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="grid")
    selected = table[table["scenario"] == "Observed-sample baseline"].drop(columns=["geometry"], errors="ignore")
    merged = grid.merge(selected, on="grid_id", suffixes=("", "_analysis"))
    merged.to_file(ROOT / "outputs/maps/baseline_proxy.gpkg", layer="baseline_proxy", driver="GPKG", engine="pyogrio")
    merged.to_crs("EPSG:4326").to_file(ROOT / "outputs/maps/baseline_proxy.geojson", driver="GeoJSON", engine="pyogrio")
