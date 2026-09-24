#!/usr/bin/env python3
"""Import private ferry operators (Turyol, Dentur Avrasya) from İBB's public-transport GTFS feed.

Şehir Hatları doesn't run some busy crossings (e.g. Beşiktaş–Üsküdar); private operators do, and neither of them
publishes a machine-readable timetable. İBB's GTFS feed has them, but its data dates from 2023–24, so every trip
is marked approximate. Frequency-based services ("every 15 min") are expanded into individual departures and keep
their headway so the page can say "about every N min".

Output: data/private/lines.json, same shape as data/site/lines.json plus `operator` and `approx` on each line.
"""
import json, os, re, sys, unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gtfs_durations import PKG, fetch, pier  # noqa: E402
import urllib.request  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OPERATORS = {"48": "Turyol", "33": "Dentur Avrasya"}
MIN_END_DATE = "20221231"  # services that ended before this are long gone


def secs(t):
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


def hhmm(sec):
    m = round(sec / 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def days_of(cal):
    d = []
    if any(cal[k] == "1" for k in ("monday", "tuesday", "wednesday", "thursday", "friday")):
        d.append("weekday")
    if cal["saturday"] == "1":
        d.append("saturday")
    if cal["sunday"] == "1":
        d.append("sunday")
    return d


def title(s):
    s = re.sub(r"\s*\((METRO|ÇAYIRBAŞI|Arabalı Vapur)\)", "", s, flags=re.I)
    parts = [p.strip() for p in re.split(r"\s*-\s*", s) if p.strip()]
    return " - ".join(pier(p) or " ".join(w[:1] + w[1:].replace("I", "ı").replace("İ", "i").lower() for w in p.split())
                      for p in parts)


def main():
    res = {r["name"]: r["url"] for r in json.load(urllib.request.urlopen(PKG, timeout=60))["result"]["resources"]}
    routes = {r["route_id"]: r for r in fetch("routes", res["routes"]) if r["agency_id"] in OPERATORS}
    cal = {c["service_id"]: c for c in fetch("calendar", res["calendar"])}
    trips = {t["trip_id"]: t for t in fetch("trips", res["trips"]) if t["route_id"] in routes}
    stops = {s["stop_id"]: s["stop_name"] for s in fetch("stops", res["stops"])}
    freqs = defaultdict(list)
    for f in fetch("frequencies", res["frequencies"]):
        if f["trip_id"] in trips:
            freqs[f["trip_id"]].append(f)
    times = defaultdict(list)
    for st in fetch("stop_times", res["stop_times"]):
        if st["trip_id"] in trips:
            times[st["trip_id"]].append(st)

    # (route, stop pattern, departure times) -> set of day types; merges duplicate services
    runs = defaultdict(set)
    headway = {}
    skipped = defaultdict(int)
    for tid, t in trips.items():
        c = cal.get(t["service_id"])
        days = days_of(c) if c and c["end_date"] >= MIN_END_DATE else []
        if not days:
            skipped["expired service"] += 1
            continue
        sts = sorted(times[tid], key=lambda s: int(s["stop_sequence"]))
        pattern = [(pier(stops.get(s["stop_id"], "")), secs(s["departure_time"])) for s in sts]
        pattern = [(p, s) for p, s in pattern if p]  # drop piers outside the planner's area (Bakırköy, Avcılar, ...)
        if len(pattern) < 2 or len({p for p, _ in pattern}) < 2:
            skipped["fewer than 2 known piers"] += 1
            continue
        base = pattern[0][1]
        starts = [(0, None)]
        if freqs[tid]:
            starts = []
            for f in freqs[tid]:
                h = int(f["headway_secs"])
                s = secs(f["start_time"])
                while s < secs(f["end_time"]):
                    starts.append((s - base, h // 60))
                    s += h
        for shift, hw in starts:
            key = (t["route_id"], tuple((p, s + shift) for p, s in pattern))
            runs[key] |= set(days)
            if hw:
                headway[key] = hw

    lines = {}
    for (rid, pattern), days in sorted(runs.items(), key=lambda kv: (kv[0][0], kv[0][1][0][1])):
        r = routes[rid]
        op = OPERATORS[r["agency_id"]]
        short = unicodedata.normalize("NFD", r["route_short_name"].replace("İ", "I").replace("ı", "i").lower())
        short = re.sub(r"[^a-z0-9]+", "-", "".join(ch for ch in short if not unicodedata.combining(ch))).strip("-")
        lid = f"{op.split()[0].lower()}-{short}"
        L = lines.setdefault(lid, {"id": lid, "name": title(r["route_long_name"]), "operator": op, "approx": True,
                                   "source": "İBB public-transport GTFS (2023–24)", "trips": []})
        trip = {"days": [d for d in ("weekday", "saturday", "sunday") if d in days],
                "stops": [{"stop": p, "dep": hhmm(s)} for p, s in pattern]}
        if (rid, pattern) in headway:
            trip["headway_min"] = headway[(rid, pattern)]
        L["trips"].append(trip)
    out = {"source": PKG, "lines": list(lines.values())}
    os.makedirs(os.path.join(ROOT, "data", "private"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "data", "private", "lines.json"), "w"), ensure_ascii=False, indent=1)
    for L in out["lines"]:
        print(f"{L['id']:28s} {len(L['trips']):4d}  {L['name']}")
    print("skipped:", dict(skipped))


if __name__ == "__main__":
    main()
