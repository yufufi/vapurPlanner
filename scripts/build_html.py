#!/usr/bin/env python3
"""Inline site/ferries.json + site/planner.js into scripts/template.html -> site/index.html (one self-contained page)."""
import json, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
db = json.load(open(os.path.join(ROOT, "site", "ferries.json")))
db.pop("notes", None)
page = open(os.path.join(ROOT, "scripts", "template.html")).read()
page = page.replace("/*__PLANNER__*/", open(os.path.join(ROOT, "site", "planner.js")).read())
page = page.replace("/*__DB__*/", json.dumps(db, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
# site/index.html is served as-is (GitHub Pages), so it needs its own document skeleton; the bare page body
# (for hosts that add their own skeleton, e.g. a Claude artifact) goes to .cache/artifact.html.
SKELETON = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Unofficial journey planner for Istanbul city ferries (Şehir Hatları), with transfers between lines. / İstanbul şehir hatları vapurları için resmi olmayan, aktarmalı yolculuk planlayıcı.">
<meta name="color-scheme" content="light dark">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>
</head>
<body>
%s
</body>
</html>
"""
open(os.path.join(ROOT, "site", "index.html"), "w").write(SKELETON.replace("%s", page, 1))
os.makedirs(os.path.join(ROOT, ".cache"), exist_ok=True)
open(os.path.join(ROOT, ".cache", "artifact.html"), "w").write(page)
print("wrote site/index.html", len(page.encode()) // 1024, "KB")
