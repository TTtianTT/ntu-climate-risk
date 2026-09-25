#!/usr/bin/env python3
"""Lightweight true-footprint extrusion data, display only."""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ntu_climate.io import ROOT, save_json


def main():
    buildings = gpd.read_file(ROOT / "data/processed/campus.gpkg", layer="buildings").to_crs("EPSG:4326")
    buildings = buildings[buildings.inside_campus_osm].copy()
    rows = []
    for _, row in buildings.iterrows():
        geom = row.geometry
        geometries = [geom] if geom.geom_type == "Polygon" else list(geom.geoms) if geom.geom_type == "MultiPolygon" else []
        for polygon in geometries:
            height = row.height_m
            assumed = bool(row.height_is_assumed)
            source = row.height_source
            if pd.isna(height):
                height, assumed, source = 10.0, True, "assumed 10 m display height; no OSM height/levels"
            rows.append({"osm_id": row.osm_id, "name": row["name"],
                         "polygon": [[float(lon), float(lat)] for lon, lat in polygon.exterior.coords],
                         "display_height_m": float(height), "height_source": source,
                         "height_is_assumed": assumed, "data_kind": "derived with assumed heights where needed"})
    save_json(ROOT / "data/processed/buildings_3d.json", rows)
    print(f"3D display parts: {len(rows)}, assumed heights: {sum(x['height_is_assumed'] for x in rows)}")


if __name__ == "__main__":
    main()
