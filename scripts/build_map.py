#!/usr/bin/env python3
"""Build the pier map: data/map.json (land outline as SVG paths + pier positions) and data/piers.json (lat/lon).

Sources (OpenStreetMap, © OpenStreetMap contributors, ODbL), fetched via the Overpass API and cached in .cache/map:
  - natural=coastline ways around Istanbul -> land polygons
  - amenity=ferry_terminal nodes -> pier positions (nearest match to our approximate coordinates)

Needs shapely (only for this build step): python3 -m venv .cache/venv && .cache/venv/bin/pip install shapely
Run: .cache/venv/bin/python scripts/build_map.py
"""
import json, math, os, sys, urllib.parse, urllib.request

from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge, polygonize, unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_db import COORDS  # noqa: E402  approximate pier coordinates (fallback + disambiguation)
from site_to_lines import CANON_BY_KEY, fold  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(ROOT, ".cache", "map")
BBOX = (40.80, 28.85, 41.25, 29.35)  # south, west, north, east
SEA_POINT = (41.00, 29.00)           # lat, lon in the Bosphorus mouth -> identifies the water piece
UA = "VapurPlanner/0.1 (github.com/yufufi/vapurPlanner)"
WIDTH = 1000                          # SVG units across the bbox


def overpass(name, query):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        data = urllib.parse.urlencode({"data": query}).encode()
        req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data,
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        open(path, "wb").write(urllib.request.urlopen(req, timeout=300).read())
    return json.load(open(path))


def main():
    s, w, n, e = BBOX
    kx = math.cos(math.radians((s + n) / 2))
    scale = WIDTH / ((e - w) * kx)
    height = (n - s) * scale
    proj = lambda lat, lon: (round((lon - w) * kx * scale, 1), round((n - lat) * scale, 1))

    # ---- land from coastline: split the bbox by the coastline; the piece containing the sea point is water
    coast = overpass("coast.json", f"[out:json][timeout:120];way[natural=coastline]({s},{w},{n},{e});out geom;")
    lines = [LineString([(p["lon"], p["lat"]) for p in el["geometry"]]) for el in coast["elements"]]
    frame = box(w, s, e, n)
    merged = unary_union([linemerge(lines), frame.boundary])
    pieces = list(polygonize(merged))
    sea = Point(SEA_POINT[1], SEA_POINT[0])
    water = [p for p in pieces if p.contains(sea)]
    if not water:
        raise SystemExit("no polygon contains the sea point; coastline may not be closed within the bbox")
    land = [p for p in pieces if not p.intersects(water[0]) or p.intersection(water[0]).area < 1e-12]
    land = unary_union(land).simplify(0.0003, preserve_topology=True)
    paths = []
    for poly in getattr(land, "geoms", [land]):
        if poly.area < 2e-6:
            continue  # rocks and specks
        ring = [proj(y, x) for x, y in poly.exterior.coords]
        d = "M" + "L".join(f"{x},{y}" for x, y in ring) + "Z"
        for hole in poly.interiors:
            d += "M" + "L".join(f"{x},{y}" for x, y in (proj(y, x) for x, y in hole.coords)) + "Z"
        paths.append(d)

    # ---- piers: nearest OSM ferry terminal whose name matches, else our approximate coordinates
    terms = overpass("piers.json", f"[out:json][timeout:150];nwr[amenity=ferry_terminal]({s},{w},{n},{e});out center tags;")
    used = json.load(open(os.path.join(ROOT, "site", "ferries.json")))["stops"]
    piers, report = {}, []
    for stop in used:
        ax, ay = COORDS[stop][1], COORDS[stop][0]
        best = None
        for el in terms["elements"]:
            name = el.get("tags", {}).get("name", "")
            if fold(stop) not in fold(name):
                continue
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            dist = math.hypot((lon - ax) * kx, lat - ay) * 111
            if dist < 3 and (best is None or dist < best[0]):
                best = (dist, lat, lon)
        lat, lon = (best[1], best[2]) if best else COORDS[stop]
        report.append(f"{stop}: {'OSM' if best else 'approx'}")
        piers[stop] = {"lat": round(lat, 5), "lon": round(lon, 5), "xy": proj(lat, lon)}

    out = {"attribution": "© OpenStreetMap contributors (ODbL)", "width": WIDTH, "height": round(height, 1),
           "land": paths, "piers": {k: v["xy"] for k, v in piers.items()}}
    json.dump(out, open(os.path.join(ROOT, "data", "map.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump({k: [v["lat"], v["lon"]] for k, v in piers.items()}, open(os.path.join(ROOT, "data", "piers.json"), "w"),
              ensure_ascii=False, indent=1)
    size = os.path.getsize(os.path.join(ROOT, "data", "map.json"))
    print(f"{len(paths)} land shapes, {len(piers)} piers, map.json {size // 1024} KB")
    print(", ".join(r for r in report if r.endswith("approx")))


if __name__ == "__main__":
    main()
