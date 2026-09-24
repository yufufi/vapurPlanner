#!/usr/bin/env python3
"""Fetch every domestic line page from sehirhatlari.istanbul and extract its timetable tables.

Output: data/scraped/html/<slug>.html (raw pages) and data/scraped/tables.json:
  { "<slug>": { "url", "title", "tables": [ { "heading": str, "rows": [[cell, ...], ...] } ] } }
Polite: one request at a time with a pause between them.
"""
import html, json, os, re, sys, time, urllib.error, urllib.request

BASE = "https://sehirhatlari.istanbul"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "scraped")
UA = "VapurPlanner/0.1 (unofficial timetable checker)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "tr,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        raise SystemExit(f"::error::GET {url} -> HTTP {e.code} {e.reason}; server={e.headers.get('server')}; body={body}")
    except OSError as e:
        raise SystemExit(f"::error::GET {url} -> {type(e).__name__}: {e}")


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<br\s*/?>", " ", re.sub(r"<[^>]+>", " ", fragment)))).strip()


def tables(page):
    out = []
    for m in re.finditer(r"<table\b.*?</table>", page, re.S):
        rows = []
        for tr in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", m.group(0), re.S):
            cells = [text(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr.group(1), re.S)]
            if any(cells):
                rows.append(cells)
        # the nearest heading-ish text before the table (direction / day-type labels live there)
        before = text(page[max(0, m.start() - 3000):m.start()])
        out.append({"context": before[-300:], "rows": rows})
    return out


def main():
    index = get(BASE + "/tr/seferler/ic-hatlar")
    links = sorted(set(re.findall(r'href="(/tr/seferler/ic-hatlar/[^/"]+/[^"]+)"', index)))
    os.makedirs(os.path.join(ROOT, "html"), exist_ok=True)
    result = {}
    for path in links:
        slug = path.rsplit("/", 1)[-1]
        page = get(BASE + path)
        open(os.path.join(ROOT, "html", slug + ".html"), "w").write(page)
        m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
        title = text(m.group(1)) if m else slug
        result[slug] = {"url": BASE + path, "title": title, "tables": tables(page)}
        print(f"{slug}: {len(result[slug]['tables'])} tables", file=sys.stderr)
        time.sleep(1.5)
    json.dump(result, open(os.path.join(ROOT, "tables.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
