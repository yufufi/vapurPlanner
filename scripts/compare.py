#!/usr/bin/env python3
"""Cross-check the PDF transcription (data/pdf) against the scraped site timetable (data/site).

Compares every printed (pier, day type, time) call in both sources and writes data/compare-report.md.
Differences are either transcription errors on one side, or genuine differences between PDF and site.
"""
import collections, glob, json, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def calls(lines):
    out = collections.defaultdict(set)  # (stop, day, time) -> line ids
    for L in lines:
        if L.get("tour"):
            continue
        for t in L["trips"]:
            for s in t["stops"]:
                tm = s.get("dep") or s.get("arr")
                if not tm:
                    continue
                h, m = map(int, tm.split(":"))
                tm = f"{h % 24:02d}:{m:02d}"  # compare wall-clock times
                for d in t["days"]:
                    out[(s["stop"], d, tm)].add(L["id"])
    return out


def main():
    pdf = [L for f in sorted(glob.glob(os.path.join(ROOT, "data", "pdf", "*.json"))) for L in json.load(open(f))["lines"]]
    site = json.load(open(os.path.join(ROOT, "data", "site", "lines.json")))["lines"]
    a, b = calls(pdf), calls(site)
    only_pdf = sorted(set(a) - set(b))
    only_site = sorted(set(b) - set(a))
    by_stop = collections.defaultdict(lambda: [[], []])
    for k in only_pdf:
        by_stop[k[0]][0].append(k)
    for k in only_site:
        by_stop[k[0]][1].append(k)
    rep = ["# PDF vs site timetable check", "",
           f"Calls compared: PDF {len(a)}, site {len(b)}, in both {len(set(a) & set(b))}.",
           f"Only in PDF: {len(only_pdf)}. Only on site: {len(only_site)}.", ""]
    for stop in sorted(by_stop):
        p, s = by_stop[stop]
        rep.append(f"## {stop}")
        for tag, items, src in (("PDF only", p, a), ("site only", s, b)):
            if items:
                rep.append(f"- **{tag}**: " + ", ".join(f"{d} {t} ({'/'.join(sorted(src[(st, d, t)]))})" for st, d, t in items))
        rep.append("")
    open(os.path.join(ROOT, "data", "compare-report.md"), "w").write("\n".join(rep))
    print("\n".join(rep[:5]))


if __name__ == "__main__":
    main()
