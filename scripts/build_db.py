#!/usr/bin/env python3
"""Build site/ferries.json, the planner's database.

Inputs:
  data/site/lines.json      timetable scraped from sehirhatlari.istanbul (primary source)
  data/pdf/*.json           transcription of the timetable PDF (used for the Bosphorus tours, which the
                            scraped line pages don't cover; scripts/compare.py cross-checks the rest)
  data/gtfs-durations.json  measured crossing times from İBB's GTFS feed

- converts "HH:MM" to minutes (24:xx+ allowed),
- fills times the operator doesn't publish (arrivals on departure-only lines, circuit returns). Sources, in order:
  measured GTFS crossing time for that pier pair -> the same pair in the current timetable -> straight-line distance
  at a speed calibrated on the timetable. Filled stops get "est": "gtfs" | "timetable" | "distance",
- attaches approximate pier coordinates and optional walking links between neighbouring piers.
"""
import json, glob, math, os, statistics, sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Approximate pier coordinates (lat, lon)
COORDS = {
    "Eminönü": (41.0176, 28.9744), "Karaköy": (41.0222, 28.9770), "Kabataş": (41.0336, 28.9930),
    "Beşiktaş": (41.0416, 29.0065), "Ortaköy": (41.0473, 29.0265), "Arnavutköy": (41.0674, 29.0430),
    "Bebek": (41.0772, 29.0440), "Rumeli Hisarı": (41.0845, 29.0560), "Emirgan": (41.1045, 29.0560),
    "İstinye": (41.1140, 29.0590), "Yeniköy": (41.1210, 29.0700), "Sarıyer": (41.1680, 29.0570),
    "Rumeli Kavağı": (41.1830, 29.0740), "Anadolu Kavağı": (41.1760, 29.0880), "Beykoz": (41.1340, 29.0930),
    "Paşabahçe": (41.1180, 29.0930), "Çubuklu": (41.1070, 29.0820), "Kanlıca": (41.0990, 29.0660),
    "Anadolu Hisarı": (41.0830, 29.0660), "Küçüksu": (41.0790, 29.0660), "Kandilli": (41.0730, 29.0590),
    "Vaniköy": (41.0640, 29.0620), "Çengelköy": (41.0510, 29.0500), "Beylerbeyi": (41.0450, 29.0450),
    "Kuzguncuk": (41.0350, 29.0310), "Üsküdar": (41.0270, 29.0130), "Harem": (41.0100, 29.0080),
    "Kadıköy": (40.9930, 29.0220), "Moda": (40.9830, 29.0240), "Bostancı": (40.9530, 29.0930),
    "Maltepe": (40.9230, 29.1310), "Kartal": (40.8870, 29.1880), "Pendik": (40.8750, 29.2350),
    "Tuzla": (40.8160, 29.3000), "Kınalıada": (40.9110, 29.0520), "Burgazada": (40.8800, 29.0660),
    "Heybeliada": (40.8770, 29.1000), "Büyükada": (40.8740, 29.1270), "Sedef Adası": (40.8560, 29.1470),
    "Kasımpaşa": (41.0340, 28.9670), "Fener": (41.0310, 28.9510), "Balat": (41.0370, 28.9480),
    "Hasköy": (41.0400, 28.9450), "Ayvansaray": (41.0430, 28.9420), "Sütlüce": (41.0500, 28.9440),
    "Eyüpsultan": (41.0480, 28.9340), "Haliç": (41.0350, 28.9560), "Aşiyan": (41.0850, 29.0540),
    "Büyükdere": (41.1590, 29.0470),
}

# Walking links between piers that are genuinely close (minutes). Off by default in the planner.
WALKS = [
    ("Karaköy", "Eminönü", 15), ("Kabataş", "Beşiktaş", 20), ("Beşiktaş", "Ortaköy", 25),
    ("Arnavutköy", "Bebek", 20), ("Üsküdar", "Harem", 25), ("Üsküdar", "Kuzguncuk", 25),
    ("Kadıköy", "Moda", 20), ("Anadolu Hisarı", "Küçüksu", 8), ("Kandilli", "Küçüksu", 15),
    ("Emirgan", "İstinye", 25), ("Fener", "Balat", 10), ("Balat", "Ayvansaray", 12),
    ("Hasköy", "Sütlüce", 15), ("Sarıyer", "Rumeli Kavağı", 45),
]


PRIVATE_KMH = 25       # typical cruising speed of the private operators' motorboats
PRIVATE_DOCK_MIN = 2   # manoeuvring in and out of the piers


def to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def km(a, b):
    (la1, lo1), (la2, lo2) = COORDS[a], COORDS[b]
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    y = math.radians(la2 - la1)
    return 6371 * math.hypot(x, y)


def main():
    site = json.load(open(os.path.join(ROOT, "data", "site", "lines.json")))
    lines, issues = site["lines"], [f"site: {i}" for i in site.get("issues", [])]
    notes = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "pdf", "*.json"))):
        d = json.load(open(f))
        lines += [L for L in d["lines"] if L.get("tour")]
        notes += d.get("general_notes", [])
    ppath = os.path.join(ROOT, "data", "private", "lines.json")
    if os.path.exists(ppath):
        lines += json.load(open(ppath))["lines"]  # Turyol / Dentur, marked operator + approx
    gtfs = {}
    gpath = os.path.join(ROOT, "data", "gtfs-durations.json")
    if os.path.exists(gpath):
        for k, v in json.load(open(gpath))["durations"].items():
            gtfs[tuple(k.split("|"))] = v["min"]

    # normalise times
    for L in lines:
        for n, tr in enumerate(L["trips"]):
            tr["id"] = f'{L["id"]}#{n}'
            for s in tr["stops"]:
                t = s.pop("arr", None) or s.pop("dep", None)
                s.pop("arr", None); s.pop("dep", None)
                if t:
                    s["t"] = to_min(t)

    # Private operators: İBB's feed pads their crossing times (e.g. 17 min for the 1.7 km Beşiktaş–Üsküdar hop, i.e.
    # ~6 km/h). Keep each trip's first departure, but where the feed's crossing is slower than a motorboat at
    # PRIVATE_KMH plus PRIVATE_DOCK_MIN for docking, use that instead and mark the time as estimated ("model").
    for L in lines:
        if not L.get("operator"):
            continue
        for tr in L["trips"]:
            st = tr["stops"]
            orig = [s["t"] for s in st]
            for i in range(1, len(st)):
                a, b = st[i - 1]["stop"], st[i]["stop"]
                if a not in COORDS or b not in COORDS:
                    continue
                model = round(PRIVATE_DOCK_MIN + km(a, b) * 60 / PRIVATE_KMH)
                feed = orig[i] - orig[i - 1]
                if model < feed:
                    st[i]["t"] = st[i - 1]["t"] + model
                    st[i]["est"] = "model"
                else:
                    st[i]["t"] = st[i - 1]["t"] + feed

    # observed direct travel times between consecutive timed stops
    seg = defaultdict(list)
    for L in lines:
        if L.get("operator"):
            continue
        for tr in L["trips"]:
            timed = [s for s in tr["stops"] if "t" in s]
            for a, b in zip(timed, timed[1:]):
                idx_a, idx_b = tr["stops"].index(a), tr["stops"].index(b)
                if idx_b == idx_a + 1 and b["t"] > a["t"]:
                    seg[(a["stop"], b["stop"])].append(b["t"] - a["t"])
    pair = {}
    for (a, b), v in seg.items():
        pair.setdefault((a, b), []).extend(v)
        pair.setdefault((b, a), []).extend(v)
    pair = {k: statistics.median(v) for k, v in pair.items()}

    # calibrate: minutes = c0 + km / speed
    pts = [(km(a, b), m) for (a, b), m in pair.items() if a in COORDS and b in COORDS and a < b]
    if len(pts) > 5:
        mx = statistics.mean(p[0] for p in pts); my = statistics.mean(p[1] for p in pts)
        slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
        c0 = my - slope * mx
    else:
        slope, c0 = 60 / 22, 4
    slope = max(slope, 1.5); c0 = max(c0, 2)

    missing = set()

    def est(a, b):
        """(minutes, source) for sailing a -> b directly."""
        for key in ((a, b), (b, a)):
            if key in gtfs:
                return gtfs[key], "gtfs"
        if (a, b) in pair:
            return pair[(a, b)], "timetable"
        if a in COORDS and b in COORDS:
            return round(c0 + slope * km(a, b)), "distance"
        missing.update(x for x in (a, b) if x not in COORDS)
        return 15, "distance"

    # fill missing times forward (and backward for a leading gap)
    for L in lines:
        for tr in L["trips"]:
            st = tr["stops"]
            first = next((i for i, s in enumerate(st) if "t" in s), None)
            if first is None:
                issues.append(f"trip {tr['id']} has no times; dropped"); tr["drop"] = True; continue
            for i in range(first - 1, -1, -1):
                m, src = est(st[i]["stop"], st[i + 1]["stop"])
                st[i]["t"] = st[i + 1]["t"] - round(m); st[i]["est"] = src
            for i in range(first + 1, len(st)):
                if "t" not in st[i]:
                    m, src = est(st[i - 1]["stop"], st[i]["stop"])
                    st[i]["t"] = st[i - 1]["t"] + round(m); st[i]["est"] = src
            for a, b in zip(st, st[1:]):
                if b["t"] < a["t"]:
                    issues.append(f"trip {tr['id']} times decrease {a['stop']} {a['t']} -> {b['stop']} {b['t']}")
        L["trips"] = [t for t in L["trips"] if not t.pop("drop", False)]

    used = sorted({s["stop"] for L in lines for t in L["trips"] for s in t["stops"]})
    db = {
        "source": "Şehir Hatları timetable (sehirhatlari.istanbul line pages + winter 2026–27 PDF), unofficial copy",
        "built": __import__("datetime").date.today().isoformat(),
        "stops": {s: ({"lat": COORDS[s][0], "lon": COORDS[s][1]} if s in COORDS else {}) for s in used},
        "lines": lines,
        "walks": [{"a": a, "b": b, "min": m} for a, b, m in WALKS if a in used and b in used],
        "notes": notes,
        "model": {"minutes_per_km": round(slope, 2), "base_min": round(c0, 1)},
    }
    json.dump(db, open(os.path.join(ROOT, "site", "ferries.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    est_counts = __import__("collections").Counter(s.get("est") for L in lines for t in L["trips"] for s in t["stops"] if s.get("est"))
    print("estimated stop times by source:", dict(est_counts))
    ntrips = sum(len(L["trips"]) for L in lines)
    print(f"{len(lines)} lines, {ntrips} trips, {len(used)} stops; est model {c0:.1f} + {slope:.2f}*km")
    if missing:
        print("stops without coordinates:", sorted(missing))
    for i in issues:
        print("ISSUE:", i)


if __name__ == "__main__":
    sys.exit(main())
