"""Scarica con un browser vero (Playwright) le pagine che caricano i contenuti con JavaScript.

Salva l'HTML gia' completo in rendered/<nome>.html; monitor.py lo legge al posto della pagina "vuota".
Rispetta il Crawl-delay del sito (3 secondi tra una pagina e l'altra).
"""
import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import monitor

OUT = Path(__file__).resolve().parent / "rendered"
STATS = Path(__file__).resolve().parent / "render_stats.json"   # quanti link aveva l'ultima versione completa di ogni pagina
MIN_RATIO = 0.8
ATTEMPTS = 3
DATA_CALLS = ("SecData", "ShowData", "LibraryFeed", "CalFeed")


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    jobs = []
    for src in monitor.SOURCES:
        if src.get("rendered_dir"):
            jobs += [(u, src.get("delay", 3.0)) for u in src.get("pages", [])]
    try:
        stats = json.loads(STATS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        stats = {}
    ok = 0
    log_lines = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=monitor.USER_AGENT, locale="en-US", viewport={"width": 1280, "height": 900})
        for url, delay in jobs:
            best, best_n = None, -1
            diag = [f"{url}"]
            for attempt in range(ATTEMPTS):
                try:
                    page = ctx.new_page()
                    mark = len(diag)
                    page.on("response", lambda resp: resp.status >= 400 and diag.append(f"  HTTP {resp.status} {resp.url[:140]}"))
                    page.on("requestfailed", lambda rq: diag.append(f"  FALLITA {rq.url[:140]} {rq.failure}"))
                    page.goto(url, wait_until="networkidle", timeout=90000)
                    page.wait_for_timeout(4000 + 4000 * attempt)   # i widget a volte compilano l'elenco in ritardo (o per niente)
                    n = page.evaluate("document.querySelectorAll('a[href]').length")
                    html = page.content()
                    page.close()
                    diag.append(f"tentativo {attempt + 1}: {n} link")
                    if n > best_n:
                        best, best_n = html, n
                    data_failed = any(k in d for d in diag[mark:] for k in DATA_CALLS)   # la richiesta che riempie l'elenco e' fallita
                    if n >= MIN_RATIO * stats.get(url, 0) and not data_failed:
                        break
                    print(f"pagina incompleta ({n} link, prima {stats.get(url, 0)}, richiesta dati fallita: {data_failed}), riprovo: {url}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print("errore", url, e, flush=True)
                time.sleep(5)
            log_lines.extend(diag[:40])
            if best is not None:
                (OUT / (monitor.rendered_slug(url) + ".html")).write_text(best, encoding="utf-8")
                stats[url] = max(best_n, stats.get(url, 0))
                ok += 1
                print("ok", url, len(best), best_n, "link", flush=True)
            time.sleep(delay)
        browser.close()
    (STATS.parent / "render_log.txt").write_text(chr(10).join(log_lines), encoding="utf-8")
    STATS.write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print(f"{ok}/{len(jobs)} pagine scaricate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
