# Vapur Planner

An **unofficial** journey planner for Istanbul's city ferries (Şehir Hatları). Pick two piers and a time; it
finds routes that use one or more boats, lines up the transfers, and shows how long you'll wait at each pier.

Not affiliated with Şehir Hatları A.Ş. Always check the [official timetable](https://sehirhatlari.istanbul/tr)
before you travel: sailings can be cancelled for weather, leave early when full, or change without notice.

İstanbul şehir hatları vapurları için **resmi olmayan**, aktarmalı bir yolculuk planlayıcı. Şehir Hatları A.Ş. ile
bir bağlantısı yoktur.

## How it works

The planner is one static page (`site/index.html`) with the timetable and routing engine inlined. It runs
entirely in the browser.

- **Routing** (`site/planner.js`): RAPTOR-style search. For every boat leaving your pier in the chosen window it
  finds the earliest arrival using 1–4 boats, then keeps the options worth showing: an option is hidden when another
  leaves no earlier and arrives sooner, counting each extra boat as a 15-minute cost.
- **Day types**: weekday / Saturday / Sunday-and-holiday timetables, plus Friday and Saturday night boats.
  Public holidays for the timetable period are listed in `planner.js`.

## Data

| File | What |
|---|---|
| `data/scraped/` | Raw line pages and tables from sehirhatlari.istanbul (`scripts/scrape.py`) |
| `data/site/lines.json` | Those tables converted to trips (`scripts/site_to_lines.py`) — **primary source** |
| `data/pdf/*.json` | Transcription of the winter 2026–27 timetable PDF, used to cross-check the site and for the Bosphorus tours |
| `data/compare-report.md` | PDF vs site differences (`scripts/compare.py`) |
| `data/gtfs-durations.json` | Measured crossing times from İBB's open GTFS feed (`scripts/gtfs_durations.py`) |
| `data/private/lines.json` | Private operators Turyol and Dentur Avrasya from the same GTFS feed (`scripts/gtfs_private.py`) |
| `site/ferries.json` | The planner's database (`scripts/build_db.py`) |

Some lines only publish departure times (e.g. Kadıköy–Beşiktaş). For those, arrival times are calculated from the
measured crossing time in İBB open data, else from the same crossing on another current line, else from distance.
Every calculated time is marked with `est` in the database and `~` in the page.

Some crossings (e.g. Beşiktaş–Üsküdar, Karaköy–Üsküdar) are run by private operators, not Şehir Hatları. They're
included by default (a checkbox turns them off), labelled with the operator's name and marked approximate: İBB's feed
dates from 2023–24, and Dentur's frequent lines are published only as "every N minutes". The feed's crossing times
for these boats are padded (17 min for the 1.7 km Beşiktaş–Üsküdar hop), so `build_db.py` recomputes them from
distance at a typical motorboat speed (`PRIVATE_KMH`, `PRIVATE_DOCK_MIN`) whenever that is faster.

## Updating

Run `scripts/update.sh` from a normal home or office connection. It re-scrapes the line pages, rebuilds the
database and page, and commits and pushes any changes; every push to `main` deploys `site/` to GitHub Pages.
Scraping can't run in GitHub Actions: the operator's site sits behind Cloudflare, which blocks datacenter IPs.

Command-line planner: `node scripts/plan_cli.js kadikoy sariyer 2026-10-03 09:00`.
