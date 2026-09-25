#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.analysis import export_analysis, scenario_table
from ntu_climate.io import ROOT


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/default.yaml")
    args = p.parse_args()
    cfg = yaml.safe_load((ROOT / args.config).read_text())
    obs_path = ROOT / "data/processed/observations.parquet"
    if not obs_path.exists():
        raise SystemExit("No real processed observations. Run build_dataset.py first.")
    observations = pd.read_parquet(obs_path)
    grid = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="grid")
    table, summary, rain = scenario_table(grid, observations, cfg)
    export_analysis(table, summary, rain, cfg)
    print(json.dumps({"qualified_for_proxy": summary["qualified_for_proxy"],
                      "baseline_H": summary["heat"]["0.0"],
                      "grid_cells": len(grid), "rainfall": rain["status"]}, indent=2))


if __name__ == "__main__":
    main()
