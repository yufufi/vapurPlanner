#!/bin/sh
# Refresh the timetable from sehirhatlari.istanbul and publish.
# Run this from a normal (home/office) connection: the site's Cloudflare protection blocks
# datacenter IPs such as GitHub Actions runners, so scraping can't happen in CI.
set -e
cd "$(dirname "$0")/.."
python3 scripts/scrape.py
python3 scripts/site_to_lines.py
python3 scripts/compare.py
python3 scripts/build_db.py
python3 scripts/build_html.py
git add data site
if git diff --cached --quiet; then
  echo "Timetable unchanged."
else
  git commit -m "Update timetable from sehirhatlari.istanbul ($(date +%F))"
  git push   # the push triggers the GitHub Pages deploy
fi
