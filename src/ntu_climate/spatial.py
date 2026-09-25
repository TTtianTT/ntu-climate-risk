"""Read real OSM XML and build projected campus screening grid."""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .io import ROOT

METRIC_CRS = "EPSG:3414"  # Singapore SVY21, metres
WGS84 = "EPSG:4326"
WALK_TYPES = {"footway", "path", "pedestrian", "steps", "living_street", "residential", "service", "unclassified", "tertiary", "secondary", "primary", "track"}
NO_WALK = {"no", "private"}


def covered_class(tags: dict) -> str:
    value = tags.get("covered", "").strip().lower()
    if value in {"yes", "true", "1"}:
        return "yes"
    if value in {"no", "false", "0"}:
        return "no"
    return "unknown"


def walkable(tags: dict) -> bool:
    return (tags.get("highway") in WALK_TYPES and tags.get("foot", "").lower() not in NO_WALK
            and tags.get("access", "").lower() not in NO_WALK)


def _row(element, tags, geom, **kwargs):
    return dict(osm_type=element.tag, osm_id=element.get("id"), name=tags.get("name", ""),
                tags_json=json.dumps(tags, ensure_ascii=False), geometry=geom, **kwargs)


def parse_osm(path=None) -> dict[str, gpd.GeoDataFrame]:
    path = path or ROOT / "data/raw/osm/ntu_bbox.osm"
    root = ET.parse(path).getroot()
    nodes = {n.get("id"): (float(n.get("lon")), float(n.get("lat"))) for n in root.findall("node")}
    buildings, walks, pois, campuses = [], [], [], []
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        refs = [n.get("ref") for n in way.findall("nd")]
        if len(refs) < 2 or any(ref not in nodes for ref in refs):
            continue
        coords = [nodes[ref] for ref in refs]
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        if tags.get("amenity") == "university" and "nanyang technological" in tags.get("name", "").lower() and closed:
            geom = Polygon(coords)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if not geom.is_empty:
                campuses.append(_row(way, tags, geom))
        if "building" in tags and closed:
            geom = Polygon(coords)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            height_source = "unknown"
            height_m = np.nan
            height_is_assumed = False
            if tags.get("height"):
                try:
                    height_m = float(tags["height"].replace(" m", ""))
                    height_source = "OSM height tag"
                except ValueError:
                    pass
            if math.isnan(height_m) and tags.get("building:levels"):
                try:
                    height_m = float(tags["building:levels"]) * 3.2
                    height_source = "OSM levels × assumed 3.2 m"
                    height_is_assumed = True
                except ValueError:
                    pass
            buildings.append(_row(way, tags, geom, height_m=height_m, height_source=height_source,
                                  height_is_assumed=height_is_assumed))
        if walkable(tags):
            walks.append(_row(way, tags, LineString(coords), highway=tags.get("highway", ""),
                              foot=tags.get("foot", ""), access=tags.get("access", ""),
                              covered=tags.get("covered", ""), covered_class=covered_class(tags),
                              tunnel=tags.get("tunnel", ""), bridge=tags.get("bridge", ""),
                              layer=tags.get("layer", "")))
    for node in root.findall("node"):
        tags = {t.get("k"): t.get("v") for t in node.findall("tag")}
        if tags.get("name") and (tags.get("amenity") or tags.get("tourism")):
            pois.append(_row(node, tags, Point(nodes[node.get("id")]), category=tags.get("amenity", tags.get("tourism", ""))))
    def gdf(rows):
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84) if rows else gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=WGS84)
    campus = gdf(campuses)
    if campus.empty:
        # Explicit approximate extent, never labelled an official campus boundary.
        campus = gpd.GeoDataFrame([_row(root, {"name": "Approximate study extent — not an official campus boundary"},
                                         box(103.670, 1.335, 103.695, 1.365))], geometry="geometry", crs=WGS84)
        campus["boundary_status"] = "approximate bbox"
    else:
        campus["boundary_status"] = "OSM amenity=university; unofficial, field verification needed"
        campus = campus.sort_values("osm_id").iloc[[campus.to_crs(METRIC_CRS).area.argmax()]]
    boundary = campus.geometry.iloc[0]
    buildings = gdf(buildings)
    walks = gdf(walks)
    pois = gdf(pois)
    for layer in (buildings, walks, pois):
        if not layer.empty:
            layer["inside_campus_osm"] = layer.geometry.representative_point().within(boundary)
    return {"campus": campus, "buildings": buildings, "walks": walks, "pois": pois}


def make_grid(campus: gpd.GeoDataFrame, walks: gpd.GeoDataFrame, size_m: int = 100) -> gpd.GeoDataFrame:
    boundary = campus.to_crs(METRIC_CRS).geometry.iloc[0]
    walk_m = walks.to_crs(METRIC_CRS)
    walk_m = walk_m[walk_m.geometry.intersects(boundary)].copy()
    if not walk_m.empty:
        walk_m["geometry"] = walk_m.geometry.intersection(boundary)
    # Union by class prevents repeated mapping or way splits from counting the same segment twice.
    merged = {}
    for category in ("yes", "no", "unknown"):
        parts = walk_m.loc[walk_m["covered_class"] == category, "geometry"].tolist() if not walk_m.empty else []
        merged[category] = unary_union(parts) if parts else None
    minx, miny, maxx, maxy = boundary.bounds
    rows = []
    for x in np.arange(math.floor(minx / size_m) * size_m, maxx, size_m):
        for y in np.arange(math.floor(miny / size_m) * size_m, maxy, size_m):
            geom = box(x, y, x + size_m, y + size_m).intersection(boundary)
            if geom.is_empty or geom.area < 1:
                continue
            lengths = {key: merged[key].intersection(geom).length if merged[key] is not None else 0.0 for key in merged}
            total = sum(lengths.values())
            if total <= 0:
                continue
            rows.append(dict(grid_id=f"E{int(x)}_N{int(y)}", area_m2=geom.area,
                             walk_m=total, covered_yes_m=lengths["yes"],
                             covered_no_m=lengths["no"], covered_unknown_m=lengths["unknown"],
                             unknown_fraction=lengths["unknown"] / total,
                             geometry=geom))
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=METRIC_CRS)


def save_spatial(layers: dict[str, gpd.GeoDataFrame], grid: gpd.GeoDataFrame, station: dict | None = None) -> dict:
    output = ROOT / "data/processed/campus.gpkg"
    if output.exists():
        output.unlink()
    all_layers = dict(layers, grid=grid)
    if station:
        loc = station["location"]
        all_layers["stations"] = gpd.GeoDataFrame([dict(station_id=station["id"], name=station["name"],
                                                      geometry=Point(loc["longitude"], loc["latitude"]))], crs=WGS84)
    counts = {}
    for name, gdf in all_layers.items():
        if gdf.empty:
            counts[name] = 0
            continue
        gdf.to_file(output, layer=name, driver="GPKG", engine="pyogrio", append=output.exists())
        web_path = ROOT / "data/processed" / f"{name}.geojson"
        gdf.to_crs(WGS84).to_file(web_path, driver="GeoJSON", engine="pyogrio")
        counts[name] = len(gdf)
    return counts
