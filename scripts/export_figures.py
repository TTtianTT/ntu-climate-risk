#!/usr/bin/env python3
"""Export reproducible static evidence; never invent unsupported weather values."""
import json
import os
import sys
from pathlib import Path

_cache = Path(__file__).resolve().parents[1] / "data/metadata/render_cache"
_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import geopandas as gpd
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, record, save_json


def footer(fig, text):
    fig.text(0.02, 0.015, text, fontsize=8, color="#475569")


def main():
    summary = json.loads((ROOT / "data/processed/summary.json").read_text())
    analysis = json.loads((ROOT / "outputs/tables/analysis_summary.json").read_text())
    period = f"{min(summary['days'])} to {max(summary['days'])} SGT"
    campus = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="campus").to_crs("EPSG:3414")
    buildings = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="buildings").to_crs("EPSG:3414")
    walks = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="walks").to_crs("EPSG:3414")
    grid = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="grid")
    station = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="stations").to_crs("EPSG:3414")
    fig, ax = plt.subplots(figsize=(8, 10))
    campus.boundary.plot(ax=ax, color="#1d4ed8", linewidth=2, label="OSM university boundary")
    buildings[buildings.inside_campus_osm].plot(ax=ax, color="#94a3b8", linewidth=0, label="OSM building")
    colors = {"yes": "#15803d", "no": "#ea580c", "unknown": "#64748b"}
    for cls, color in colors.items():
        selection = walks[(walks.inside_campus_osm) & (walks.covered_class == cls)]
        if not selection.empty:
            selection.plot(ax=ax, color=color, linewidth=0.7, label=f"covered={cls}")
    station.plot(ax=ax, color="#1e3a8a", markersize=35, label="S44")
    ax.set_title("NTU campus OSM geometry and S44 station")
    ax.set_aspect("equal")
    ax.legend(handles=[Line2D([0], [0], color="#1d4ed8", lw=2, label="OSM university boundary"),
                       Patch(facecolor="#94a3b8", label="OSM building"),
                       *[Line2D([0], [0], color=color, lw=1, label=f"covered={cls}") for cls, color in colors.items()],
                       Line2D([0], [0], marker="o", color="w", markerfacecolor="#1e3a8a", label="S44")],
              loc="upper right", fontsize=8)
    ax.set_xlabel("SVY21 easting (m)")
    ax.set_ylabel("SVY21 northing (m)")
    footer(fig, "OSM © contributors · NEA/data.gov.sg · OSM boundary is unofficial; not all bbox buildings are NTU assets")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(ROOT / "outputs/maps/campus_map.png", dpi=180)
    plt.close(fig)

    hourly = pd.read_csv(ROOT / "data/processed/hourly_quality.csv")
    daily = pd.read_csv(ROOT / "data/processed/daily_quality.csv")
    hourly.to_csv(ROOT / "outputs/tables/weather_timeseries.csv", index=False)
    daily.to_csv(ROOT / "outputs/tables/data_completeness.csv", index=False)
    hourly["time"] = pd.to_datetime(hourly.local_day + " " + hourly.hour.astype(str).str.zfill(2) + ":00")
    fig, axs = plt.subplots(4, 1, figsize=(13, 9), sharex=True)
    labels = {"temperature": "Air temperature (°C)", "humidity": "Relative humidity (%)",
              "rainfall": "Observed rainfall (mm/h)", "wind_speed": "Wind speed (m/s)"}
    for ax, (var, label) in zip(axs, labels.items()):
        data = hourly[hourly.variable == var]
        ax.plot(data.time, data.value, linewidth=0.8)
        ax.set_ylabel(label)
        ax.grid(alpha=0.2)
    axs[0].set_title(f"S44 Nanyang Avenue · observed hourly summaries · {period}")
    axs[-1].set_xlabel("Asia/Singapore local time")
    footer(fig, "NEA/data.gov.sg · partial rainfall hours retain partial sums; missing hours remain missing")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(ROOT / "outputs/figures/weather_timeseries.png", dpi=170)
    plt.close(fig)

    matrix = daily.pivot(index="variable", columns="local_day", values="coverage").reindex(list(labels))
    fig, ax = plt.subplots(figsize=(max(10, len(matrix.columns) * 0.36), 3.5))
    im = ax.imshow(matrix.to_numpy(), aspect="auto", vmin=0, vmax=1, cmap="Blues")
    ax.set_yticks(range(len(matrix)), matrix.index)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=65, ha="right", fontsize=7)
    ax.set_title(f"S44 observation coverage by local day · {period}")
    fig.colorbar(im, ax=ax, label="Valid / expected intervals")
    footer(fig, "NEA/data.gov.sg · engineering completeness threshold: 80%; no missing interval is set to zero")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(ROOT / "outputs/figures/data_completeness.png", dpi=170)
    plt.close(fig)

    table = pd.read_csv(ROOT / "outputs/tables/grid_scenarios.csv")
    base = table[table.scenario == "Observed-sample baseline"]
    warm = table[table.scenario == "Warming +2°C"]
    shelter = table[table.scenario == "Shelter 50%"]
    base[["grid_id", "proxy_degC_h_m"]].merge(warm[["grid_id", "proxy_degC_h_m"]], on="grid_id", suffixes=("_baseline", "_warming2")).to_csv(ROOT / "outputs/tables/baseline_vs_warming.csv", index=False)
    base[["grid_id", "proxy_degC_h_m"]].merge(shelter[["grid_id", "proxy_degC_h_m"]], on="grid_id", suffixes=("_baseline", "_shelter50")).to_csv(ROOT / "outputs/tables/baseline_vs_shelter.csv", index=False)
    vmax = analysis["common_color_max"] or 1
    for other, name, title in [(warm, "baseline_vs_warming", "Baseline vs +2°C sensitivity"),
                                (shelter, "baseline_vs_shelter", "Baseline vs selected-cell 50% shelter sensitivity")]:
        fig, axs = plt.subplots(1, 2, figsize=(13, 7))
        for ax, data, subtitle in zip(axs, (base, other), ("Observed-sample baseline", other.scenario.iloc[0])):
            merged = grid.merge(data[["grid_id", "proxy_degC_h_m"]], on="grid_id")
            merged.plot(ax=ax, column="proxy_degC_h_m", cmap="YlOrRd", vmin=0, vmax=vmax,
                        edgecolor="#475569", linewidth=0.15,
                        missing_kwds={"color": "#9ca3af"})
            if name == "baseline_vs_shelter":
                grid[grid.grid_id.isin(analysis["selected_grid_ids"])].boundary.plot(ax=ax, color="#1d4ed8", linewidth=1.1)
            ax.set_title(subtitle)
            ax.set_axis_off()
            ax.set_aspect("equal")
        sm = plt.cm.ScalarMappable(cmap="YlOrRd", norm=plt.Normalize(0, vmax))
        fig.colorbar(sm, ax=axs, label="Proxy (°C·h·m)", shrink=0.7)
        change = next(s["change_pct"] for s in analysis["scenarios"] if s["name"] == other.scenario.iloc[0])
        fig.suptitle(f"{title} · {period}\nTotal proxy change {change:+.1f}% (formula sensitivity)")
        footer(fig, "OSM © contributors · NEA S44 · q_unknown=0.5 assumed · same time mask and color scale; not health risk")
        fig.savefig(ROOT / f"outputs/figures/{name}.png", dpi=170, bbox_inches="tight")
        plt.close(fig)
    print("Saved campus map, weather time series, completeness, and two common-scale comparisons")


if __name__ == "__main__":
    main()
