#!/usr/bin/env python3
"""Measure typical crossing times between piers from İBB's public-transport GTFS feed.

The current timetable prints only departures for some lines (e.g. Kadıköy–Beşiktaş), so arrival times there
must be estimated. This script downloads the city's GTFS feed (data.ibb.gov.tr, "public-transport-gtfs-data"),
keeps Şehir Hatları trips (agency 6), and writes the median sailing time for every consecutive pier pair to
data/gtfs-durations.json. The feed's timetable is older than ours, but crossing times rarely change.
"""
import csv, io, json, os, re, statistics, sys, unicodedata, urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from site_to_lines import CANON_BY_KEY, fold  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(ROOT, ".cache", "gtfs")
PKG = "https://data.ibb.gov.tr/api/3/action/package_show?id=public-transport-gtfs-data"
AGENCY = "6"  # Şehir Hatları A.Ş.


def fetch(name, url):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".csv")
    if not os.path.exists(path):
        print("downloading", name, file=sys.stderr)
        urllib.request.urlretrieve(url, path)
    raw = open(path, "rb").read()
    for enc in ("utf-8", "iso-8859-9"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(enc).lstrip("﻿"))))
        except UnicodeDecodeError:
            continue


def pier(name):
    """Map a GTFS stop name ('KADIKÖY İSKELESİ', 'Beşiktaş Vapur İskelesi', ...) to our pier names."""
    k = fold(re.sub(r"(?i)(iskelesi|iskele|vapur|arabalı|şehir hatları|\(.*?\))", " ", name))
    if k.startswith("eyup"):
        return "Eyüpsultan"
    for key, canon in sorted(CANON_BY_KEY.items(), key=lambda kv: -len(kv[0])):
        if key in k:
            return canon
    return None


def to_min(t):
    h, m, *_ = map(int, t.split(":"))
    return h * 60 + m


def main():
    res = {r["name"]: r["url"] for r in json.load(urllib.request.urlopen(PKG, timeout=60))["result"]["resources"]}
    routes = {r["route_id"] for r in fetch("routes", res["routes"]) if r["agency_id"] == AGENCY}
    trips = {t["trip_id"] for t in fetch("trips", res["trips"]) if t["route_id"] in routes}
    stops = {s["stop_id"]: s["stop_name"] for s in fetch("stops", res["stops"])}
    by_trip = defaultdict(list)
    for st in fetch("stop_times", res["stop_times"]):
        if st["trip_id"] in trips:
            by_trip[st["trip_id"]].append(st)
    seg, unmapped = defaultdict(list), set()
    for tid, sts in by_trip.items():
        sts.sort(key=lambda s: int(s["stop_sequence"]))
        for a, b in zip(sts, sts[1:]):
            pa, pb = pier(stops.get(a["stop_id"], "")), pier(stops.get(b["stop_id"], ""))
            for p, s in ((pa, a), (pb, b)):
                if not p:
                    unmapped.add(stops.get(s["stop_id"], s["stop_id"]))
            if pa and pb and pa != pb:
                d = to_min(b["arrival_time"]) - to_min(a["departure_time"])
                if 0 < d < 180:
                    seg[f"{pa}|{pb}"].append(d)
    out = {k: {"min": round(statistics.median(v)), "n": len(v)} for k, v in sorted(seg.items())}
    json.dump({"source": PKG, "durations": out}, open(os.path.join(ROOT, "data", "gtfs-durations.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(by_trip)} ferry trips, {len(out)} pier pairs")
    if unmapped:
        print("unmapped stop names:", sorted(unmapped)[:30], file=sys.stderr)


if __name__ == "__main__":
    main()
