"""Cadenza dei comunicati stampa di Gorilla: distanza tra uno e l'altro, media, e a che punto siamo.

Storico in pr_history.json (partenza da pr_seed.txt, poi si aggiorna da solo con la pagina IR).
Statistica descrittiva sui comunicati passati: non prevede il futuro e non e' un consiglio.
"""
import gzip
import hashlib
import html
import json
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIST = HERE / "pr_history.json"
SEED = HERE / "pr_seed.txt"
PR_URL = "https://investors.gorilla-technology.com/press-releases/"
WINDOW_DAYS = 365          # gli ultimi 12 mesi descrivono meglio il ritmo di oggi
RECENT_DAYS = 180
LOOK_AHEAD = 7             # "entro altri 7 giorni"
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

RX_NOTICE = re.compile(r"conference call|sets .*call|to announce .*results|investor webinar|to host", re.I)
RX_RESULTS = re.compile(r"\b(reports?|releases?)\b.*(results|quarter|full year|audited|revenue|financials)|"
                        r"revenue (surges|up)|doubles revenue|record revenue|converts growth|exceeds .* expectations", re.I)
RX_MONEY = re.compile(r"offering|pricing of|convertible|atm programme|registered direct|shelf registration", re.I)
RX_NOISE = re.compile(r"^(correction|update)\b", re.I)


def kind(title):
    if RX_NOTICE.search(title):
        return "avviso"
    if RX_MONEY.search(title):
        return "finanziamento"
    if RX_RESULTS.search(title) and not RX_NOTICE.search(title):
        return "risultati"
    return "altro"


# ----------------------------- STORICO -----------------------------
def load():
    if HIST.exists():
        try:
            return json.loads(HIST.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    items = []
    if SEED.exists():
        for ln in SEED.read_text(encoding="utf-8").splitlines():
            if "|" in ln:
                d, t = ln.split("|", 1)
                items.append({"d": d.strip(), "t": t.strip()})
    return items


def save(items):
    items = sorted(items, key=lambda x: (x["d"], x["t"]), reverse=True)
    HIST.write_text(json.dumps(items, ensure_ascii=False, indent=0), encoding="utf-8")
    return items


def read_snapshot():
    """Comunicati visibili ora nella pagina IR (prima pagina dell'elenco), dallo snapshot del monitor."""
    f = HERE / "snapshots" / (hashlib.sha1(PR_URL.encode()).hexdigest()[:16] + ".json.gz")
    if not f.exists():
        return []
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        lines = json.load(fh).get("lines", [])
    out = []
    for i, x in enumerate(lines[:-3]):
        if re.fullmatch(r"\d{1,2}", x) and lines[i + 1] in MONTHS and re.fullmatch(r"20\d\d", lines[i + 2]):
            d = f"{lines[i + 2]}-{MONTHS[lines[i + 1]]:02d}-{int(x):02d}"
            out.append({"d": d, "t": lines[i + 3].strip()})
    return out


def update():
    items = load()
    have = {(x["d"], x["t"][:40].lower()) for x in items}
    new = [x for x in read_snapshot() if (x["d"], x["t"][:40].lower()) not in have]
    items = save(items + new)
    return items, new


# ----------------------------- STATISTICHE -----------------------------
def pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def analyse(items, today=None):
    today = today or datetime.now(timezone.utc).date()
    days = sorted({date.fromisoformat(x["d"]) for x in items})   # piu' comunicati nello stesso giorno contano uno
    if len(days) < 5:
        return None
    last = days[-1]
    since = (today - last).days
    res = {"last": last, "since": since, "today": today, "n_total": len(items)}
    for key, span in (("y", WINDOW_DAYS), ("h", RECENT_DAYS)):
        sel = [d for d in days if (today - d).days <= span]
        gaps = [(b - a).days for a, b in zip(sel, sel[1:])]
        if len(gaps) < 3:
            res[key] = None
            continue
        g = sorted(gaps)
        res[key] = {"n": len(sel), "mean": statistics.mean(gaps), "median": statistics.median(gaps),
                    "p75": pct(g, 0.75), "p90": pct(g, 0.90), "max": g[-1], "gaps": gaps}
    y = res.get("y")
    if y:
        longer = [g for g in y["gaps"] if g > since]
        res["survival"] = None
        if longer:
            soon = [g for g in longer if g <= since + LOOK_AHEAD]
            res["survival"] = (len(soon), len(longer))
        res["pos"] = ("sotto la mediana" if since <= y["median"] else
                      "oltre la mediana, sotto la media" if since <= y["mean"] else
                      "oltre la media, sotto il 75º percentile" if since <= y["p75"] else
                      "oltre il 75º percentile" if since <= y["max"] else "oltre il massimo degli ultimi 12 mesi")
        res["level"] = (0 if since <= y["median"] else 1 if since <= y["mean"] else 2 if since <= y["p75"] else 3)
    # prossimo appuntamento fisso: i risultati dello stesso periodo dell'anno scorso
    res["next_results"] = next_results(items, today)
    res["gaps_last"] = []
    seq = days[-13:]
    res["gaps_last"] = [((b - a).days, b) for a, b in zip(seq, seq[1:])]
    return res


def next_results(items, today):
    res_days = sorted({date.fromisoformat(x["d"]) for x in items if kind(x["t"]) == "risultati"})
    last_res = max((d for d in res_days if d <= today), default=None)
    cand = [d for d in res_days if today - timedelta(days=365) <= d <= today - timedelta(days=365) + timedelta(days=80)]
    if not cand or (last_res and (today - last_res).days < 20):
        return None
    ly = cand[0]
    notice = [date.fromisoformat(x["d"]) for x in items if kind(x["t"]) == "avviso"
              and 0 < (ly - date.fromisoformat(x["d"])).days <= 10]
    exp = ly + timedelta(days=365)
    return {"last_year": ly, "expected": exp, "notice_lead": (ly - max(notice)).days if notice else None,
            "last_results": last_res}


# ----------------------------- PAGINA -----------------------------
def e(s):
    return html.escape(str(s))


def fmt(d):
    return d.strftime("%d/%m/%Y")


def render_html(items=None, today=None):
    items = items if items is not None else load()
    r = analyse(items, today)
    if not r or not r.get("y"):
        return ""
    y, h = r["y"], r.get("h")
    lvl = r["level"]
    tone = ["ok", "warn", "warn", "bad"][lvl]
    head = {0: "Siamo dentro il ritmo normale", 1: "Siamo oltre la mediana", 2: "Siamo oltre la media",
            3: "Siamo oltre il solito"}[lvl]
    surv = ""
    if r.get("survival"):
        a, b = r["survival"]
        surv = (f"<li>Nei {y['n']} comunicati degli ultimi 12 mesi, tra le attese più lunghe di {r['since']} giorni, "
                f"<strong>{a} su {b}</strong> si sono chiuse con un nuovo comunicato entro altri {LOOK_AHEAD} giorni"
                f"{' (campione molto piccolo: poco affidabile)' if b < 10 else ''}.</li>")
    elif lvl == 3:
        surv = f"<li>Un'attesa di {r['since']} giorni non c'è stata negli ultimi 12 mesi: il confronto storico non regge.</li>"
    nr = r.get("next_results")
    cal = ""
    if nr:
        lead = f", con avviso circa {nr['notice_lead']} giorni prima" if nr["notice_lead"] is not None else ""
        cal = (f"<li><strong>Appuntamento fisso:</strong> i risultati dello stesso periodo sono usciti il {fmt(nr['last_year'])}{lead}. "
               f"Da calendario, la finestra più probabile è intorno al <strong>{fmt(nr['expected'])}</strong>"
               f" (±1-2 settimane; la data si conosce solo con l'avviso della conference call).</li>")
    # barre: ultimi 12 intervalli + attesa attuale
    gl = r["gaps_last"]
    mx = max([g for g, _ in gl] + [r["since"], 1])
    bars = "".join(
        f'<div class="gb"><span class="gd">{fmt(d)}</span><span class="gbar" style="width:{max(2, 100 * g / mx):.0f}%">{g} g</span></div>'
        for g, d in gl[::-1])
    now_bar = (f'<div class="gb"><span class="gd">oggi</span><span class="gbar now" style="width:{max(2, 100 * r["since"] / mx):.0f}%">'
               f'{r["since"]} g dall\'ultimo</span></div>')
    stats = (f"<tr><td>Ultimi 12 mesi ({y['n']} comunicati)</td><td>{y['median']:.0f}</td><td>{y['mean']:.1f}</td>"
             f"<td>{y['p75']:.0f}</td><td>{y['max']}</td></tr>")
    if h:
        stats += (f"<tr><td>Ultimi 6 mesi ({h['n']} comunicati)</td><td>{h['median']:.0f}</td><td>{h['mean']:.1f}</td>"
                  f"<td>{h['p75']:.0f}</td><td>{h['max']}</td></tr>")
    return f"""<h2>Cadenza dei comunicati</h2>
<div class="cad">
<div class="cadh {tone}"><strong>{head}</strong><span class="small"> · ultimo comunicato: {fmt(r['last'])} ({r['since']} giorni fa) · {r['pos']}</span></div>
<ul>{surv}{cal}</ul>
<table class="st"><tr><th>Giorni tra un comunicato e il successivo</th><th>mediana</th><th>media</th><th>75º perc.</th><th>massimo</th></tr>{stats}</table>
<details><summary>Ultimi intervalli (giorni di distanza)</summary><div class="gbars">{now_bar}{bars}</div></details>
<p class="small">Come si legge: è una statistica sui comunicati passati ({r['n_total']} dal 2022). Dice quanto spesso Gorilla ha pubblicato,
non che ne uscirà uno. Spesso i comunicati arrivano insieme ad altri eventi (risultati, emissioni di titoli), che nella cadenza non si vedono.
Non è un segnale operativo né consulenza finanziaria.</p>
</div>"""


if __name__ == "__main__":
    its, new = update()
    print(len(its), "comunicati; nuovi:", len(new))
