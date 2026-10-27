"""Scarica con un browser vero (Playwright) le pagine che caricano i contenuti con JavaScript.

Salva l'HTML gia' completo in rendered/<nome>.html; monitor.py lo legge al posto della pagina "vuota".
Rispetta il Crawl-delay del sito (3 secondi tra una pagina e l'altra).
"""
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import monitor

OUT = Path(__file__).resolve().parent / "rendered"


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    jobs = []
    for src in monitor.SOURCES:
        if src.get("rendered_dir"):
            jobs += [(u, src.get("delay", 3.0)) for u in src.get("pages", [])]
    ok = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=monitor.USER_AGENT, locale="en-US", viewport={"width": 1280, "height": 900})
        for url, delay in jobs:
            for attempt in range(2):
                try:
                    page = ctx.new_page()
                    page.goto(url, wait_until="networkidle", timeout=90000)
                    page.wait_for_timeout(4000)   # tempo ai widget di compilare gli elenchi
                    html = page.content()
                    page.close()
                    (OUT / (monitor.rendered_slug(url) + ".html")).write_text(html, encoding="utf-8")
                    ok += 1
                    print("ok", url, len(html), flush=True)
                    break
                except Exception as e:  # noqa: BLE001
                    print("errore", url, e, flush=True)
                    time.sleep(5)
            time.sleep(delay)
        browser.close()
    print(f"{ok}/{len(jobs)} pagine scaricate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
