"""Genera docs/index.html (pagina web) e STATUS.md da state.json e history.json."""
import html
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "docs" / "index.html"
MAX_EVENTS = 150

BADGES = {
    "PAGINA MODIFICATA": ("modificata", "b-mod"), "NUOVA PAGINA": ("nuova pagina", "b-new"),
    "PAGINA RIMOSSA": ("rimossa", "b-del"), "NUOVO DOCUMENTO SEC": ("documento SEC", "b-sec"),
    "CAMBIO DI MASSA": ("cambio di massa", "b-mass"), "PROBLEMA": ("problema", "b-del"),
}


def esc(s):
    return html.escape(str(s), quote=True)


def link(u, label=None, cls=""):
    u = str(u)
    if not u.startswith(("http://", "https://")):
        return esc(label or u)
    return f'<a class="{cls}" href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(label or u)}</a>'


def fmt_ts(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def load_history():
    f = HERE / "history.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))[::-1][:MAX_EVENTS]
    except Exception:  # noqa: BLE001
        return []


def row(sign, text, cls):
    return f'<div class="line {cls}"><span class="sg">{sign}</span><span>{esc(text)}</span></div>'


def render_detail(ev):
    d = ev.get("detail") or {}
    parts = []
    if ev["type"] == "NUOVA PAGINA":
        parts.append(f'<p class="muted">Pagina nuova, circa {d.get("chars", 0):,} caratteri di testo.</p>')
        return "".join(parts)
    if d.get("title"):
        parts.append('<div class="blk"><div class="lbl">Titolo</div>' + row("−", d["title"][0], "rem") + row("+", d["title"][1], "add") + "</div>")
    if d.get("desc"):
        parts.append('<div class="blk"><div class="lbl">Descrizione</div>' + row("−", d["desc"][0], "rem") + row("+", d["desc"][1], "add") + "</div>")
    if d.get("removed") or d.get("added"):
        b = '<div class="blk"><div class="lbl">Testo della pagina</div>'
        b += "".join(row("−", t, "rem") for t in d.get("removed", []))
        if d.get("n_removed", 0) > len(d.get("removed", [])):
            b += f'<div class="more">… e altre {d["n_removed"] - len(d["removed"])} righe tolte</div>'
        b += "".join(row("+", t, "add") for t in d.get("added", []))
        if d.get("n_added", 0) > len(d.get("added", [])):
            b += f'<div class="more">… e altre {d["n_added"] - len(d["added"])} righe aggiunte</div>'
        parts.append(b + "</div>")
    if d.get("links_added"):
        parts.append('<div class="blk"><div class="lbl">Link aggiunti</div>'
                     + "".join(f'<div class="line add"><span class="sg">+</span>{link(u)}</div>' for u in d["links_added"]) + "</div>")
    if d.get("links_removed"):
        parts.append('<div class="blk"><div class="lbl">Link tolti</div>'
                     + "".join(f'<div class="line rem"><span class="sg">−</span>{link(u)}</div>' for u in d["links_removed"]) + "</div>")
    if d.get("chrome"):
        parts.append(f'<p class="muted">Cambiati anche menu o piè di pagina ({d["chrome"]} caratteri).</p>')
    if not parts:   # tipi senza dettagli strutturati: mostro il testo dell'avviso, una riga per volta
        parts.append('<div class="blk">' + "".join(f'<div class="line">{esc(t)}</div>' for t in ev.get("text", [])) + "</div>")
    return "".join(parts)


def render_event(ev, sample=False):
    label, cls = BADGES.get(ev["type"], (ev["type"].lower(), "b-mod"))
    d = ev.get("detail") or {}
    title = d.get("page_title") or ev["url"]
    head_link = link(ev["url"], title, "ttl") if ev["url"].startswith("http") else f'<span class="ttl">{esc(title)}</span>'
    ts = ev["ts"]
    open_btn = link(ev["url"], "Apri la pagina ↗", "btn") if ev["url"].startswith("http") else ""
    return (f'<article class="ev{" sample" if sample else ""}" data-src="{esc(ev["source"])}">'
            f'<div class="evh"><span class="badge {cls}">{esc(label)}</span><span class="badge src">{esc(ev["source"])}</span>'
            f'<time datetime="{esc(ts)}">{esc(ts.replace("T", " ")[:16])} UTC</time></div>'
            f'<h3>{head_link}</h3><div class="url">{esc(ev["url"].split("//", 1)[-1])}</div>'
            f'{render_detail(ev)}<div class="foot">{open_btn}</div></article>')


SAMPLE = {
    "ts": "2026-01-01T12:00:00+00:00", "source": "Gorilla IR", "type": "PAGINA MODIFICATA",
    "url": "https://investors.gorilla-technology.com/press-releases/",
    "text": [], "detail": {
        "page_title": "Press Releases | Gorilla Technology", "title": None, "desc": None,
        "removed": [], "n_removed": 0,
        "added": ["Gorilla Technology announces ... (titolo del nuovo comunicato)"], "n_added": 1,
        "links_added": ["https://investors.gorilla-technology.com/news-releases/esempio"], "links_removed": [], "chrome": 0},
}


def main():
    st = json.loads((HERE / "state.json").read_text(encoding="utf-8-sig"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hist = load_history()
    sources = [n for n in st["sources"] if n != "EDGAR"]
    cards, tables = [], []
    last_all = 0
    for name in sources:
        s = st["sources"][name]
        pages = s.get("pages", {})
        last = max((p.get("checked", 0) for p in pages.values()), default=0)
        last_all = max(last_all, last)
        fails = st.get("fails", {}).get(name, 0)
        status = '<span class="ok">● attivo</span>' if not fails else f'<span class="bad">● {fails} errori di fila</span>'
        n_ev = sum(1 for e in hist if e["source"] == name)
        cards.append(f'<div class="card"><h3>{esc(name)}</h3><div class="big">{len(pages)}</div><div class="muted">pagine monitorate</div>'
                     f'<div class="small">{status}<br>{n_ev} modifiche registrate</div></div>')
        rows = "".join(f'<tr><td>{link(u, p.get("title") or u)}</td><td class="small">{esc(u.split("//", 1)[-1])}</td></tr>'
                       for u, p in sorted(pages.items()))
        tables.append(f'<details><summary>{esc(name)}: elenco pagine ({len(pages)})</summary><table>{rows}</table></details>')

    if hist:
        feed = "".join(render_event(e) for e in hist)
    else:
        feed = ('<div class="empty"><strong>Nessuna modifica rilevata finora.</strong><br>Il confronto parte dalla situazione '
                'registrata al primo avvio. Quando una pagina cambia compare qui, con le righe tolte e aggiunte e i link per aprirla. '
                'Così apparirà (esempio):</div>' + render_event(SAMPLE, sample=True))
    filters = '<button class="on" data-f="">Tutti</button>' + "".join(
        f'<button data-f="{esc(n)}">{esc(n)}</button>' for n in sources)

    page = f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Gorilla Watch</title>
<style>
:root{{--bg:#f5f6f8;--fg:#14171c;--card:#fff;--line:#dde1e7;--mut:#667085;--ok:#137a3d;--bad:#b42318;--acc:#1d4ed8;
--addbg:#e6f6ec;--addfg:#14532d;--rembg:#fdecea;--remfg:#7f1d1d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1116;--fg:#e6e9ee;--card:#171b22;--line:#2a313c;--mut:#98a2b3;--ok:#4ade80;--bad:#f87171;--acc:#7aa2ff;
--addbg:#12301f;--addfg:#a7f3c0;--rembg:#3a1717;--remfg:#fecaca}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
main{{max-width:900px;margin:0 auto;padding:22px 16px 64px}}
h1{{margin:0;font-size:26px}} h2{{margin:30px 0 10px;font-size:18px}}
.muted,.small{{color:var(--mut)}} .small{{font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-top:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 15px}}
.card h3{{margin:0 0 4px;font-size:14px}} .big{{font-size:28px;font-weight:650;line-height:1.1}}
.ok{{color:var(--ok);font-weight:600}} .bad{{color:var(--bad);font-weight:600}}
.filters{{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 12px}}
.filters button{{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}}
.filters button.on{{background:var(--acc);border-color:var(--acc);color:#fff}}
.ev{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}}
.ev.sample{{opacity:.6;border-style:dashed}}
.evh{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}} time{{margin-left:auto;font-size:12.5px;color:var(--mut)}}
.badge{{font-size:12px;font-weight:600;padding:2px 9px;border-radius:999px;border:1px solid var(--line)}}
.b-mod{{background:#fff4d6;color:#7a4b00;border-color:#f3d98b}} .b-new{{background:#e6f6ec;color:#14532d;border-color:#a7dfbb}}
.b-del{{background:#fdecea;color:#7f1d1d;border-color:#f3b3ad}} .b-sec{{background:#e8edff;color:#1e3a8a;border-color:#b7c5f5}}
.b-mass{{background:#f0e6ff;color:#4c1d95;border-color:#cdb5f2}} .src{{color:var(--mut)}}
.ev h3{{margin:10px 0 0;font-size:17px;line-height:1.3}} .ttl{{color:var(--fg);text-decoration:none}} .ttl:hover{{color:var(--acc);text-decoration:underline}}
.url{{font-size:12.5px;color:var(--mut);word-break:break-all;margin-bottom:6px}}
.blk{{margin:10px 0}} .lbl{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin-bottom:4px;font-weight:600}}
.line{{display:flex;gap:8px;padding:4px 8px;border-radius:6px;margin:2px 0;word-break:break-word;font-size:14px}}
.line .sg{{font-weight:700;width:12px;flex:none}}
.line.add{{background:var(--addbg);color:var(--addfg)}} .line.rem{{background:var(--rembg);color:var(--remfg)}}
.line a{{color:inherit;word-break:break-all}} .more{{font-size:13px;color:var(--mut);padding:2px 8px}}
.foot{{margin-top:10px}} .btn{{display:inline-block;font-size:13px;padding:5px 12px;border:1px solid var(--acc);border-radius:8px;text-decoration:none}}
.empty{{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px 16px;color:var(--fg)}}
details{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:8px 0}}
summary{{cursor:pointer;font-weight:600}} table{{width:100%;border-collapse:collapse;margin-top:8px}}
td{{padding:5px 6px;border-top:1px solid var(--line);vertical-align:top;word-break:break-word}} a{{color:var(--acc)}}
</style></head><body><main>
<h1>Gorilla Watch</h1>
<p class="muted">Controllo automatico di Gorilla Technology, Gorilla Tech Capital e Investor Relations, ogni 30 minuti circa.
Ultimo controllo: <strong>{fmt_ts(last_all)}</strong> · pagina generata: {now}. Segnala solo modifiche vere ai contenuti.</p>
<div class="cards">{''.join(cards)}</div>
<h2>Modifiche rilevate</h2>
<div class="filters">{filters}</div>
<div id="feed">{feed}</div>
<h2>Pagine monitorate</h2>{''.join(tables)}
<p class="small">Strumento personale e non ufficiale. Non è consulenza finanziaria: verificare sempre sui documenti originali.</p>
</main>
<script>
document.querySelectorAll('.filters button').forEach(function(b){{b.onclick=function(){{
 document.querySelectorAll('.filters button').forEach(function(x){{x.classList.remove('on')}});b.classList.add('on');
 var f=b.dataset.f;document.querySelectorAll('.ev').forEach(function(e){{e.style.display=(!f||e.dataset.src===f)?'':'none'}});}}}});
document.querySelectorAll('time[datetime]').forEach(function(t){{var d=new Date(t.getAttribute('datetime'));if(isNaN(d))return;
 var m=Math.round((Date.now()-d)/60000),s=m<60?m+' min fa':m<1440?Math.round(m/60)+' ore fa':Math.round(m/1440)+' giorni fa';
 t.textContent=d.toLocaleString('it-IT',{{dateStyle:'short',timeStyle:'short'}})+' ('+s+')';}});
</script></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print("scritto", OUT)
    write_status(st, now, hist, sources)


def write_status(st, now, hist, sources):
    """STATUS.md: GitHub la mostra formattata nel repository."""
    md = ["# Gorilla Watch", "", f"Ultimo aggiornamento: **{now}**", "",
          "| Sito | Pagine | Ultimo controllo | Stato |", "|---|---|---|---|"]
    for name in sources:
        pages = st["sources"][name].get("pages", {})
        last = max((p.get("checked", 0) for p in pages.values()), default=0)
        fails = st.get("fails", {}).get(name, 0)
        md.append(f"| {name} | {len(pages)} | {fmt_ts(last)} | {'ok' if not fails else str(fails) + ' errori di fila'} |")
    md += ["", "## Ultime modifiche rilevate", ""]
    if not hist:
        md.append("Nessuna modifica rilevata finora.")
    for ev in hist[:20]:
        d = ev.get("detail") or {}
        md.append(f"### [{d.get('page_title') or ev['url']}]({ev['url']})")
        md.append(f"{ev['ts'][:16].replace('T', ' ')} UTC · {ev['source']} · {ev['type'].lower()}")
        md.append("")
        for t in d.get("removed", []):
            md.append(f"- ~~{t}~~")
        for t in d.get("added", []):
            md.append(f"- **{t}**")
        for u in d.get("links_added", []):
            md.append(f"- link aggiunto: {u}")
        for u in d.get("links_removed", []):
            md.append(f"- link tolto: {u}")
        if not d:
            md.extend(f"- {t}" for t in ev.get("text", []))
        md.append("")
    md += ["", "_Strumento personale. Non è consulenza finanziaria: verificare sui documenti originali._"]
    (HERE / "STATUS.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
