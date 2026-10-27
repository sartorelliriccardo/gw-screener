"""Genera docs/index.html (la pagina pubblica) da state.json e alerts.log."""
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "docs" / "index.html"
MAX_ALERTS = 40


def read_alerts():
    f = HERE / "alerts.log"
    if not f.exists():
        return []
    txt = f.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"^=== (.+?) ===\n", txt, flags=re.M)
    out = []
    for i in range(1, len(blocks) - 1, 2):
        out.append((blocks[i], blocks[i + 1].strip()))
    return out[::-1][:MAX_ALERTS]


def fmt_ts(ts):
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    st = json.loads((HERE / "state.json").read_text(encoding="utf-8-sig"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards, tables = [], []
    for name, s in st["sources"].items():
        if name == "EDGAR":
            cards.append(f'<div class="card"><h3>EDGAR</h3><p>{len(s.get("seen", []))} documenti noti</p></div>')
            continue
        pages = s.get("pages", {})
        last = max((p.get("checked", 0) for p in pages.values()), default=0)
        fails = st.get("fails", {}).get(name, 0)
        status = '<span class="ok">ok</span>' if not fails else f'<span class="bad">{fails} errori di fila</span>'
        cards.append(f'<div class="card"><h3>{html.escape(name)}</h3><p class="big">{len(pages)}</p>'
                     f'<p>pagine monitorate</p><p class="small">ultimo controllo {fmt_ts(last)}<br>stato: {status}</p></div>')
        rows = "".join(
            f'<tr><td><a href="{html.escape(u)}" rel="noopener">{html.escape(p.get("title") or u)}</a></td>'
            f'<td class="small">{html.escape(u.split("//", 1)[-1])}</td></tr>'
            for u, p in sorted(pages.items(), key=lambda kv: kv[0]))
        tables.append(f'<details><summary>{html.escape(name)}: elenco pagine ({len(pages)})</summary>'
                      f'<table>{rows}</table></details>')
    alerts = read_alerts()
    if alerts:
        al = "".join(f'<div class="alert"><div class="ts">{html.escape(ts)}</div>'
                     f'<pre>{html.escape(body)}</pre></div>' for ts, body in alerts)
    else:
        al = '<p class="muted">Nessuna modifica rilevata finora. Il confronto parte dalla base creata al primo avvio.</p>'

    page = f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Gorilla Watch</title>
<style>
:root{{--bg:#f6f7f9;--fg:#15181d;--card:#fff;--line:#dfe3e8;--mut:#667085;--ok:#137a3d;--bad:#b42318;--acc:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1116;--fg:#e6e9ee;--card:#171b22;--line:#2a313c;--mut:#98a2b3;--ok:#4ade80;--bad:#f87171;--acc:#7aa2ff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px 64px}}
h1{{margin:0 0 4px;font-size:26px}} h2{{margin:32px 0 12px;font-size:18px}}
.muted,.small{{color:var(--mut)}} .small{{font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.card h3{{margin:0 0 6px;font-size:15px}} .card p{{margin:2px 0}} .big{{font-size:30px;font-weight:650}}
.ok{{color:var(--ok);font-weight:600}} .bad{{color:var(--bad);font-weight:600}}
.alert{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:8px;padding:10px 14px;margin:10px 0}}
.ts{{font-weight:600;font-size:13px;color:var(--mut)}}
pre{{white-space:pre-wrap;word-break:break-word;margin:6px 0 0;font:13px/1.45 ui-monospace,Consolas,monospace}}
details{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:8px 0}}
summary{{cursor:pointer;font-weight:600}} table{{width:100%;border-collapse:collapse;margin-top:8px}}
td{{padding:5px 6px;border-top:1px solid var(--line);vertical-align:top;word-break:break-word}}
a{{color:var(--acc)}}
</style></head><body><main>
<h1>Gorilla Watch</h1>
<p class="muted">Controllo automatico dei siti Gorilla Technology, Gorilla Tech Capital e IR, ogni 30 minuti.
Pagina aggiornata: {now}. Mostra solo modifiche di contenuto, non cambi di data.</p>
<div class="cards">{''.join(cards)}</div>
<h2>Ultime modifiche rilevate</h2>{al}
<h2>Pagine monitorate</h2>{''.join(tables)}
<p class="small">Strumento personale, non ufficiale. Non è consulenza finanziaria: verificare sempre sui documenti originali.</p>
</main></body></html>"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print("scritto", OUT)
    write_status(st, now, alerts)


def write_status(st, now, alerts):
    """STATUS.md: GitHub la mostra formattata nel repository (anche privato)."""
    md = ["# Gorilla Watch", "", f"Ultimo aggiornamento: **{now}**", "",
          "| Sito | Pagine | Ultimo controllo | Stato |", "|---|---|---|---|"]
    for name, s in st["sources"].items():
        if name == "EDGAR":
            continue
        pages = s.get("pages", {})
        last = max((p.get("checked", 0) for p in pages.values()), default=0)
        fails = st.get("fails", {}).get(name, 0)
        md.append(f"| {name} | {len(pages)} | {fmt_ts(last)} | {'ok' if not fails else str(fails) + ' errori di fila'} |")
    md += ["", "## Ultime modifiche rilevate", ""]
    if not alerts:
        md.append("Nessuna modifica rilevata finora.")
    for ts, body in alerts[:15]:
        md += [f"**{ts}**", "", "```", body, "```", ""]
    md += ["", "_Strumento personale. Non è consulenza finanziaria: verificare sui documenti originali._"]
    (HERE / "STATUS.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
