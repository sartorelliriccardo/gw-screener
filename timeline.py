"""Pagina "Cronologia e diluizioni": tutti i comunicati in ordine di data, le diluizioni vere (da dilution.json)
e, per ogni raccolta, cosa e' uscito nei 30 giorni prima e nei 14 dopo."""
import html
import json
from datetime import date, datetime, timezone
from pathlib import Path

import cadence

HERE = Path(__file__).resolve().parent
KIND_LABEL = {"avviso": ("avviso", "k-av"), "risultati": ("risultati", "k-res"), "finanziamento": ("finanziamento", "k-fin"),
              "altro": ("", "")}
DIL_LABEL = {"effettiva": ("diluizione effettiva", "d-eff"), "potenziale": ("diluizione potenziale", "d-pot"),
             "riduzione": ("riduzione azioni", "d-red"), "tecnica": ("operazione tecnica", "d-tec")}


def e(s):
    return html.escape(str(s))


def fmt(d):
    return d.strftime("%d/%m/%Y")


def load_dilution():
    f = HERE / "dilution.json"
    try:
        return sorted(json.loads(f.read_text(encoding="utf-8")), key=lambda x: x["d"])
    except Exception:  # noqa: BLE001
        return []


def dil_card(x):
    lab, cls = DIL_LABEL.get(x["kind"], ("", ""))
    src = f' <a href="{e(x["src"])}" target="_blank" rel="noopener noreferrer">fonte ↗</a>' if x.get("src") else ""
    return (f'<div class="dil {cls}"><div class="dh"><span class="bd">{e(lab)}</span><strong>{e(x["title"])}</strong>'
            f'<span class="dd">{fmt(date.fromisoformat(x["d"]))}</span></div>'
            f'<div class="dl"><span>Azioni:</span> {e(x["shares"])}</div>'
            f'<div class="dl"><span>Prezzo:</span> {e(x["price"])}</div>'
            f'<div class="dn">{e(x["note"])}{src}</div></div>')


def raise_map(items, rows, today):
    """Per ogni raccolta: i comunicati dei 30 giorni prima e dei 14 dopo, con la distanza in giorni."""
    out = []
    for r in rows[::-1]:
        t0 = r["d"]
        seq = sorted({(date.fromisoformat(x["d"]), x["t"]) for x in items
                      if -30 <= (date.fromisoformat(x["d"]) - t0).days <= 14})
        li = []
        for d, t in seq:
            off = (d - t0).days
            k = cadence.kind(t)
            hit = " raise" if off == 0 and cadence.RX_RAISE.search(t) else ""
            lab = "stesso giorno" if off == 0 else (f"{off:+d} g")
            li.append(f'<li class="{k}{hit}"><span class="of">{lab}</span><span class="nm">{e(t)}</span>'
                      f'{"<span class=bd>" + KIND_LABEL[k][0] + "</span>" if KIND_LABEL[k][0] else ""}</li>')
        out.append(f'<details><summary>{fmt(t0)} · {e(r["what"])} · {r["after_res"] if r["after_res"] is not None else "-"} giorni dopo i risultati</summary>'
                   f'<ul class="map">{"".join(li)}</ul></details>')
    return "".join(out)


def chrono(items, dil):
    by_year = {}
    entries = [(x["d"], 0, x["t"]) for x in items] + [(x["d"], 1, x) for x in dil]
    entries.sort(key=lambda z: (z[0], z[1]), reverse=True)
    prev_pr = {}
    pr_days = sorted({x["d"] for x in items})
    for d, typ, v in entries:
        y = d[:4]
        if typ == 1:
            by_year.setdefault(y, []).append(dil_card(v))
            continue
        i = pr_days.index(d)
        gap = (date.fromisoformat(d) - date.fromisoformat(pr_days[i - 1])).days if i > 0 else None
        k = cadence.kind(v)
        lab, cls = KIND_LABEL[k]
        by_year.setdefault(y, []).append(
            f'<div class="pr {cls}"><span class="dt">{fmt(date.fromisoformat(d))}</span>'
            f'<span class="gp">{"+" + str(gap) + " g" if gap is not None else ""}</span>'
            f'<span class="tt">{e(v)}</span>{"<span class=bd>" + lab + "</span>" if lab else ""}</div>')
    parts = []
    for y in sorted(by_year, reverse=True):
        n = sum(1 for d, typ, _ in entries if d[:4] == y and typ == 0)
        parts.append(f'<details{" open" if y == str(datetime.now(timezone.utc).year) else ""}><summary>{y} · {n} comunicati</summary>'
                     f'{"".join(by_year[y])}</details>')
    return "".join(parts)


CSS = """:root{--bg:#f5f6f8;--fg:#14171c;--card:#fff;--line:#dde1e7;--mut:#667085;--acc:#1d4ed8;--ok:#137a3d;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--fg:#e6e9ee;--card:#171b22;--line:#2a313c;--mut:#98a2b3;--acc:#7aa2ff;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:900px;margin:0 auto;padding:22px 16px 64px}h1{margin:0;font-size:26px}h2{margin:30px 0 10px;font-size:18px}
a{color:var(--acc)}.muted,.small{color:var(--mut)}.small{font-size:13px}
.bd{font-size:11.5px;font-weight:600;padding:1px 8px;border-radius:999px;border:1px solid var(--line);margin:0 6px;white-space:nowrap}
.dil{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--mut);border-radius:10px;padding:10px 14px;margin:10px 0}
.dil.d-eff{border-left-color:#b42318}.dil.d-pot{border-left-color:#d97706}.dil.d-red{border-left-color:#137a3d}.dil.d-tec{border-left-color:#6b7280}
.dh{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.dd{margin-left:auto;color:var(--mut);font-size:13px}
.dl{font-size:14px}.dl span{color:var(--mut)}.dn{font-size:13.5px;color:var(--mut);margin-top:4px}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:8px 0}summary{cursor:pointer;font-weight:600}
.pr{display:flex;gap:10px;padding:5px 0;border-top:1px solid var(--line);align-items:baseline;font-size:14px}
.pr .dt{width:84px;flex:none;color:var(--mut)}.pr .gp{width:46px;flex:none;color:var(--mut);font-size:12px;text-align:right}.pr .tt{flex:1}
.k-fin .tt{font-weight:600}.k-res .tt{font-weight:600}
.map{list-style:none;margin:8px 0 0;padding:0}.map li{display:flex;gap:10px;padding:4px 0;border-top:1px solid var(--line);font-size:13.5px}
.map .of{width:78px;flex:none;color:var(--mut)}.map .nm{flex:1}.map li.raise{background:#fdecea;color:#7f1d1d;font-weight:600;border-radius:4px}
.map li.risultati .nm{font-weight:600}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:10px 0}
.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}.sum b{display:block;font-size:22px}
table{width:100%;border-collapse:collapse}td,th{padding:5px 6px;border-top:1px solid var(--line);text-align:left;font-size:14px}
"""


def build():
    items = cadence.load()
    dil = load_dilution()
    today = datetime.now(timezone.utc).date()
    info = cadence.raises_info(items, today)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    eff = [x for x in dil if x["kind"] == "effettiva"]
    page = f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>Gorilla Watch - Cronologia</title><style>{CSS}</style></head><body><main>
<p><a href="./">← Torna a Gorilla Watch</a></p>
<h1>Cronologia e diluizioni</h1>
<p class="muted">Tutti i comunicati di Gorilla in ordine di data, con le operazioni che hanno cambiato il numero di azioni e, per ogni raccolta di capitale,
cosa è uscito nei 30 giorni prima e nei 14 dopo. Pagina generata: {now}.</p>

<h2>Quante azioni, nel tempo</h2>
<div class="sum">
<div><span class="small">fine 2023 (dopo lo split)</span><b>circa 7,6-7,8M</b><span class="small">dato rettificato; il 20-F ha due cifre</span></div>
<div><span class="small">giugno 2024</span><b>8,97M → 11,11M</b><span class="small">dopo l'offerta da $12M</span></div>
<div><span class="small">fine 2024</span><b>circa 18-19M</b><span class="small">conversioni e warrant</span></div>
<div><span class="small">ottobre 2026 (nostra ricerca)</span><b>circa 27,6M</b><span class="small">30,7M con le azioni dei dipendenti (RSU)</span></div>
</div>
<p class="small">Da fine 2023 a oggi le azioni sono circa <strong>3,5 volte tanto</strong>. A questo si aggiunge la diluizione <em>potenziale</em> delle obbligazioni convertibili ({len(eff)} operazioni effettive e 2 potenziali qui sotto).</p>

<h2>Le diluizioni, in ordine</h2>
<p class="small">Rosso = azioni già emesse · arancione = potenziali (se le obbligazioni si convertono) · verde = riacquisti · grigio = operazioni tecniche.
Dati da prospetti e 20-F per il periodo fino al 2025; per il 2026 dalla nostra ricerca del 20/10 (stime, da verificare su EDGAR).</p>
{''.join(dil_card(x) for x in dil[::-1])}

<h2>Cosa è uscito prima e dopo ogni raccolta</h2>
<p class="small">Per ogni raccolta: comunicati dal giorno −30 al +14. La riga rossa è il giorno della raccolta, in grassetto i risultati.</p>
{raise_map(items, info["rows"], today)}

<h2>Tutti i comunicati</h2>
<p class="small">La colonna a destra della data indica i giorni dal comunicato precedente. I riquadri colorati sono le diluizioni, messe nel punto della cronologia dove sono avvenute.</p>
{chrono(items, dil)}

<p class="small">Fonti: elenco comunicati sul sito IR di Gorilla, prospetti e 20-F su SEC, comunicati Newsfile. Strumento personale e non ufficiale.
Non è consulenza finanziaria: verificare sempre sui documenti originali.</p>
</main></body></html>"""
    for p in (HERE / "docs" / "timeline.html", HERE / "timeline.html"):
        p.parent.mkdir(exist_ok=True)
        p.write_text(page, encoding="utf-8")
    return page


if __name__ == "__main__":
    build()
    print("scritto timeline.html")
