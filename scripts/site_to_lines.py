#!/usr/bin/env python3
"""Convert scraped site tables (data/scraped/tables.json) into timetable lines (data/site/lines.json).

Output uses the same shape as the PDF transcription (data/pdf/*.json):
  {"lines": [{id, name, source_url, trips: [{days, stops: [{stop, dep|arr, no_board?}], note?}]}], "issues": [...]}

Table anatomy on sehirhatlari.istanbul:
  row 0  heading: day type + footnotes ("Her gün * Pazar ve Resmi Tatil Günleri Yapılmaz ** ...")
  row 1  stop names (column order = sailing order)
  row 2  optional Kalkış/Varış row; two cells means "first column departs, last column arrives"
  rest   one row per boat, "-" = does not call; "(hh:mm)" = time of an earlier leg; markers * ** *** = footnotes
Pages whose tables have a single column are plain departure lists; each departure sails to the
other pier named on the same page (arrival time unknown).
"""
import json, os, re, sys, unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ALL = ["weekday", "saturday", "sunday"]

CANON = [
    "Eminönü", "Karaköy", "Kabataş", "Beşiktaş", "Ortaköy", "Arnavutköy", "Bebek", "Rumeli Hisarı", "Emirgan",
    "İstinye", "Yeniköy", "Büyükdere", "Sarıyer", "Rumeli Kavağı", "Anadolu Kavağı", "Beykoz", "Paşabahçe",
    "Çubuklu", "Kanlıca", "Anadolu Hisarı", "Küçüksu", "Kandilli", "Vaniköy", "Çengelköy", "Beylerbeyi",
    "Kuzguncuk", "Üsküdar", "Harem", "Kadıköy", "Moda", "Bostancı", "Maltepe", "Kartal", "Pendik", "Tuzla",
    "Kınalıada", "Burgazada", "Heybeliada", "Büyükada", "Sedef Adası", "Kasımpaşa", "Fener", "Balat", "Hasköy",
    "Ayvansaray", "Sütlüce", "Eyüpsultan", "Aşiyan",
]


def fold(s):
    s = s.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    s = unicodedata.normalize("NFD", s)
    return re.sub(r"[^a-z]", "", "".join(c for c in s if not unicodedata.combining(c)))


CANON_BY_KEY = {fold(c): c for c in CANON}
ALIASES = {"ahisari": "Anadolu Hisarı", "pendikido": "Pendik", "tuzlaido": "Tuzla"}


def stop_name(raw):
    s = re.sub(r"\((K|V|Eski|Yeni)\)", "", raw).strip()
    k = fold(s)
    if k in ALIASES:
        return ALIASES[k]
    if k in CANON_BY_KEY:
        return CANON_BY_KEY[k]
    raise ValueError(f"unknown stop name {raw!r}")


def pretty(part):
    try:
        return stop_name(part)
    except ValueError:
        return " ".join(w[:1] + tr_lower(w[1:]) for w in part.split())


def tr_lower(s):
    return s.replace("İ", "i").replace("I", "ı").lower()


def base_days(heading):
    h = tr_lower(heading.split("*")[0])
    if "cuma'yı" in h or "bağlayan geceler" in h:
        return ["friday_night", "saturday_night"]
    if re.search(r"hafta ?içi ve cumartesi", h):
        return ["weekday", "saturday"]
    if re.search(r"hafta ?içi", h):
        return ["weekday"]
    if "cumartesi, pazar" in h or "cumartesi pazar" in h:
        return ["saturday", "sunday"]
    if "cumartesi" in h:
        return ["saturday"]
    if "pazar" in h or "tatil" in h:
        return ["sunday"]
    if re.search(r"her ?gün", h):
        return list(ALL)
    raise ValueError(f"cannot read day type from heading {heading!r}")


def footnotes(heading):
    """Return {marker: text} for '* text ** text' parts of a heading."""
    out = {}
    for m in re.finditer(r"(\*+)\s*([^*]+)", heading):
        out[m.group(1)] = tr_lower(m.group(2)).strip()
    return out


def apply_day_note(days, note):
    n = note.replace(" ,", ",")
    if "yapılmaz" in n:
        if "c.tesi" in n or "cumartesi, pazar" in n or "cumartesi pazar" in n:
            return [d for d in days if d == "weekday"]
        if "cumartesi" in n:
            return [d for d in days if d != "saturday"]
        if "pazar" in n or "tatil" in n:
            return [d for d in days if d != "sunday"]
    if "yapılır" in n:
        if "cumartesi" in n:
            return ["saturday", "sunday"]
        if "pazar" in n or "tatil" in n:
            return ["sunday"]
    return days


CELL = re.compile(r"^(\()?\s*(\d{1,2})[:.](\d{2})\s*(\))?\s*(\(V\))?\s*(\*+)?$")


def parse_cell(c):
    m = CELL.match(c.strip())
    if not m:
        return None
    paren, hh, mm, _, v, star = m.groups()
    return {"t": int(hh) * 60 + int(mm), "paren": bool(paren) and not v, "arr": bool(v), "star": star or ""}


def hhmm(t):
    return f"{t // 60:02d}:{t % 60:02d}"


def convert_table(tbl, issues, where, circuit=False):
    rows = tbl["rows"]
    heading = rows[0][0]
    stops = [stop_name(s) for s in rows[1]]
    raw_names = rows[1]
    data = rows[2:]
    kinds = None
    if data and all(c in ("Kalkış", "Varış") for c in data[0]):
        kinds = data[0]
        data = data[1:]
        if len(kinds) != len(stops):  # merged header: first departs, last arrives
            kinds = ["Kalkış"] * (len(stops) - 1) + ["Varış"]
    else:
        kinds = ["Varış" if "(V)" in r else "Kalkış" for r in raw_names]
    days0 = base_days(heading)
    notes = footnotes(heading)
    night = days0 == ["friday_night", "saturday_night"]
    trips, prev_first, rollover = [], None, False
    for r in data:
        if len(r) != len(stops):
            issues.append(f"{where}: row width {len(r)} != {len(stops)}: {r}")
            continue
        cells = [parse_cell(c) for c in r]
        for c, raw in zip(cells, r):
            if c is None and raw.strip() not in ("-", "", "–"):
                issues.append(f"{where}: unreadable cell {raw!r}")
        idx = [i for i, c in enumerate(cells) if c]
        if not idx:
            continue
        # after-midnight handling: night tables, and rows that wrap past midnight at the end of a table
        first = cells[idx[0]]["t"]
        if night and first < 12 * 60:
            first += 1440
        elif prev_first is not None and first < prev_first - 360:
            rollover = True
        if rollover:
            first += 1440 if first < 1440 else 0
        prev_first = first
        days, trip_notes, stop_objs, last_t, end_cell = list(days0), [], [], None, None
        for i in idx:
            c = cells[i]
            t = c["t"] + (1440 if (night and c["t"] < 12 * 60) or rollover else 0)
            if c["arr"] and c["star"] and "bitmektedir" in notes.get(c["star"], ""):
                end_cell = (i, t)  # e.g. "(20:10)(V) *": trip ends here, printed out of column order
                days = apply_day_note(days, notes.get(c["star"], ""))
                continue
            if last_t is not None and t < last_t:
                if not c["paren"] and t + 1440 - last_t < 60:
                    t += 1440  # crossing midnight inside the trip
                else:
                    continue  # time of the boat's previous leg, printed for reference
            elif c["paren"] and last_t is None and any(not cells[j]["paren"] for j in idx if j > i) \
                    and cells[[j for j in idx if j > i][0]]["t"] < c["t"]:
                continue
            so = {"stop": stops[i]}
            note = notes.get(c["star"], "") if c["star"] else ""
            is_arr = c["arr"] or "varış saat" in note or (kinds[i] == "Varış")
            so["arr" if is_arr else "dep"] = hhmm(t)
            if "yolcu almaz" in note:
                so["no_board"] = True
            stop_objs.append(so)
            last_t = t
            if note:
                days = apply_day_note(days, note)
                if "iskele" in note and "yolcu almaz" not in note:
                    trip_notes.append(note[0].upper() + note[1:])
                if "bitmektedir" in note:
                    stop_objs[-1] = {"stop": stops[i], "arr": hhmm(t)}
        if end_cell:
            stop_objs.append({"stop": stops[end_cell[0]], "arr": hhmm(end_cell[1])})
        if circuit:
            stop_objs.append({"stop": stops[0]})  # boat returns to where it started; time not printed
        if len(stop_objs) < 2:
            if len(stops) > 1:
                issues.append(f"{where}: row with <2 stops skipped: {r}")
            continue
        # a stop marked as the end of the trip truncates everything after it
        for k, so in enumerate(stop_objs):
            n = notes.get(next((cells[i]["star"] for i in idx if stops[i] == so["stop"] and cells[i]["star"]), ""), "")
            if "bitmektedir" in n:
                stop_objs = stop_objs[:k + 1]
                break
        if not days:
            issues.append(f"{where}: footnotes removed every day for row {r}")
            continue
        trip = {"days": days, "stops": stop_objs}
        if trip_notes:
            trip["note"] = "; ".join(dict.fromkeys(trip_notes))
        trips.append(trip)
    return stops, days0, trips


def main():
    scraped = json.load(open(os.path.join(ROOT, "data", "scraped", "tables.json")))
    lines, issues = [], []
    for slug, page in scraped.items():
        name = " - ".join(pretty(p) for p in re.split(r"\s*-\s*", page["title"]) if p.strip())
        single = [t for t in page["tables"] if len(t["rows"]) > 1 and len(t["rows"][1]) == 1]
        line = {"id": re.sub(r"-\d+$", "", slug), "name": name, "source_url": page["url"], "trips": []}
        if single and len(single) == len(page["tables"]):
            piers = list(dict.fromkeys(stop_name(t["rows"][1][0]) for t in single))
            if len(piers) != 2:
                issues.append(f"{slug}: departure-list page with piers {piers}")
                continue
            for ti, t in enumerate(single):
                origin = stop_name(t["rows"][1][0])
                dest = piers[1] if origin == piers[0] else piers[0]
                _, _, trips = convert_table({"rows": t["rows"]}, issues, f"{slug}#{ti}")
                # single-column rows come back empty (need 2 stops) -> rebuild them directly
                days0, notes = base_days(t["rows"][0][0]), footnotes(t["rows"][0][0])
                start = 3 if t["rows"][2][0] in ("Kalkış", "Varış") else 2
                prev = None
                for r in t["rows"][start:]:
                    c = parse_cell(r[0])
                    if not c:
                        continue
                    tt = c["t"] + (1440 if prev is not None and c["t"] < prev - 360 else 0)
                    prev = tt
                    days = apply_day_note(list(days0), notes.get(c["star"], "")) if c["star"] else list(days0)
                    line["trips"].append({"days": days, "stops": [{"stop": origin, "dep": hhmm(tt)}, {"stop": dest}]})
            issues[:] = [i for i in issues if not i.startswith(slug + "#") or "<2 stops" not in i]
        else:
            tabs = page["tables"]
            sig = lambda t: (frozenset(t["rows"][1]), t["rows"][0][0], [sorted(r) for r in t["rows"][3:]])
            rotated = {j for i in range(len(tabs)) for j in range(i + 1, len(tabs)) if sig(tabs[i]) == sig(tabs[j])}
            # identical duplicates are simply skipped; a rotated copy means the first table is a circuit
            circuits = {i for i in range(len(tabs)) for j in rotated
                        if j > i and sig(tabs[i]) == sig(tabs[j]) and tabs[i]["rows"][1] != tabs[j]["rows"][1]}
            for ti, t in enumerate(tabs):
                if ti in rotated:
                    continue  # same boats with the columns rotated (departure lists per pier), not a return table
                _, _, trips = convert_table(t, issues, f"{slug}#{ti}", circuit=ti in circuits)
                line["trips"] += trips
            if circuits:
                line["note"] = "Circuit: each row is one boat returning to its first pier; the return arrival time is not published."
        lines.append(line)
    os.makedirs(os.path.join(ROOT, "data", "site"), exist_ok=True)
    json.dump({"lines": lines, "issues": issues}, open(os.path.join(ROOT, "data", "site", "lines.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"{len(lines)} lines, {sum(len(l['trips']) for l in lines)} trips from site")
    for i in issues:
        print("ISSUE:", i)


if __name__ == "__main__":
    sys.exit(main())
