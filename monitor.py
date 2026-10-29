"""Monitor dei contenuti dei siti Gorilla (versione 2).

Cosa controlla (solo libreria standard di Python):
  - www.gorilla-technology.com  (tutte le pagine delle sitemap Yoast)
  - www.gorillatech.capital     (Gorilla Tech Capital, tutte le pagine delle sitemap)
  - investors.gorilla-technology.com (pagine elencate in EXTRA_PAGES)
  - (opzionale) nuovi documenti su EDGAR, se imposti la variabile SEC_USER_AGENT

Cosa segnala come "modifica vera":
  pagina NUOVA / RIMOSSA, TESTO cambiato (con le righe aggiunte/tolte),
  titolo o descrizione cambiati, link aggiunti/rimossi, cambio di menu/piè di pagina.
  Un semplice cambio di data nella sitemap senza cambio di contenuto va solo nel log.

Primo avvio = crea la base di confronto (nessun avviso).
Avvisi: alerts.log (storico) e last_alert.txt (ultimo). Nessun popup (TOAST_ENABLED=False).
"""
import difflib
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse

# ----------------------------- CONFIGURAZIONE -----------------------------
SOURCES = [
    {"name": "Gorilla Technology", "sitemap_index": "https://www.gorilla-technology.com/sitemap_index.xml",
     "domains": ["gorilla-technology.com"], "delay": 1.0},
    {"name": "Gorilla Tech Capital", "sitemap_index": "https://www.gorillatech.capital/sitemap_index.xml",
     "domains": ["gorillatech.capital"], "delay": 1.0},
    # Le pagine IR caricano elenchi e documenti con JavaScript: le legge render.py con un browser vero (cartella rendered/).
    {"name": "Gorilla IR", "pages": ["https://investors.gorilla-technology.com/press-releases/",
                                     "https://investors.gorilla-technology.com/events-presentations/",
                                     "https://investors.gorilla-technology.com/quarterly-results/",
                                     "https://investors.gorilla-technology.com/annual-reports/"],
     "rendered_dir": "rendered", "track_docs": True,
     "domains": ["investors.gorilla-technology.com"], "delay": 3.0},   # robots.txt: Crawl-delay 3
]
EDGAR_CIK = ""                       # vuoto = lo ricavo dal ticker e verifico il nome della societa'
EDGAR_TICKER = "GRRR"
EDGAR_NAME_CHECK = "gorilla"
EDGAR_UA = os.environ.get("SEC_USER_AGENT", "").strip()   # es.: "Nome Cognome nome@email.it"; vuoto = disattivato
EDGAR_FORMS_OF_INTEREST = None       # None = tutti i moduli; oppure {"6-K","20-F","424B5","424B7","F-3","SC 13G","SC 13D","4","3","144","D"}

USER_AGENT = "Mozilla/5.0 (compatible; PersonalSiteMonitor/1.0; low-frequency)"
FULL_CHECK_EVERY_HOURS = 6           # rilegge comunque ogni pagina almeno ogni N ore (anche senza cambio di sitemap)
MIN_CHANGED_CHARS = 12               # ignora micro-variazioni sotto questa soglia
MAX_DIFF_LINES = 8                   # righe mostrate per pagina
MAX_PAGES_PER_SOURCE = 400
MASS_CHANGE_RATIO = 0.30             # se cambia piu' del 30% delle pagine: avviso unico "cambio di tema/manutenzione"
SHRINK_CONFIRM = 96               # controlli di fila (~4 giorni) prima di credere che una pagina IR si sia davvero svuotata (il widget a volte resta vuoto mezza giornata)
SHRINK_RATIO = 0.5                # sotto questa frazione di righe la pagina IR e' sospetta (render incompleto)
FAILS_BEFORE_ALERT = 6               # avvisa se una fonte non risponde per N controlli di fila
TOAST_ENABLED = False

# righe da ignorare nei confronti (cookie banner, anno del copyright, contatori)
IGNORE_LINE_PATTERNS = [
    r"^©", r"copyright", r"cookie", r"^loading", r"^skip to", r"^\d{1,2}:\d{2}(:\d{2})?$",
    r"^\d+ (seconds?|minutes?|hours?) ago$",
]

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
SNAP = HERE / "snapshots"
LOG = HERE / "monitor.log"
ALERTS = HERE / "alerts.log"
HISTORY = HERE / "history.json"
LAST_ALERT = HERE / "last_alert.txt"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template", "head"}
BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "main", "header", "footer", "nav", "form", "table", "blockquote", "figure"}
CHROME_TAGS = {"header", "nav", "footer"}
IGNORE_RX = [re.compile(p, re.I) for p in IGNORE_LINE_PATTERNS]
DONEW_RX = re.compile(r"DoNew\('([^']+)'\s*,\s*'([0-9A-Fa-f]+)'")
DOCEXT_RX = re.compile(r"\.(pdf|pptx?|xlsx?)$", re.I)
SKIP_URL_PATTERNS = ["cookie-policy"]   # pagine che cambiano da sole (elenco cookie con codici casuali)
MAX_FILE_MB = 40
MAX_NEW_FILES_PER_RUN = 15


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


# ----------------------------- RETE -----------------------------
def http_get(url, etag=None, last_mod=None, ua=USER_AGENT, accept="*/*"):
    """Ritorna (status, bytes|None, headers). 304 = non modificato."""
    err = None
    for attempt in range(3):
        try:
            h = {"User-Agent": ua, "Accept": accept, "Accept-Encoding": "gzip"}
            if etag:
                h["If-None-Match"] = etag
            if last_mod:
                h["If-Modified-Since"] = last_mod
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return r.status, data, r.headers
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, None, e.headers
            err = e
            if e.code in (403, 404, 410):
                break
        except Exception as e:  # noqa: BLE001
            err = e
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {err}")


# ----------------------------- ESTRAZIONE HTML -----------------------------
class Extract(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.skip = 0
        self.chrome = 0
        self.title = ""
        self.in_title = False
        self.desc = ""
        self.content, self.chrome_lines = [], []
        self.cur = []
        self.links = set()
        self.docs = {}        # url del documento -> [hash dichiarato dalla pagina, etichetta]
        self._doc = None

    def flush(self):
        t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        self.cur = []
        if t:
            (self.chrome_lines if self.chrome else self.content).append(t)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            n = (a.get("name") or a.get("property") or "").lower()
            if n in ("description", "og:description") and not self.desc:
                self.desc = (a.get("content") or "").strip()
        if tag in SKIP_TAGS and tag != "head":
            self.skip += 1
            return
        if tag in BLOCK_TAGS:
            self.flush()
        if tag in CHROME_TAGS:
            self.flush()
            self.chrome += 1
        if tag == "a" and a.get("href"):
            href = a["href"].strip()
            m = DONEW_RX.search(href)
            if m:   # link a documento del tipo javascript:DoNew('url','hash'): l'hash cambia se il file viene sostituito
                self.links.add(f"{m.group(1)}#sha={m.group(2)[:16]}")
                self._doc = [m.group(1), m.group(2), ""]
                self.docs.setdefault(m.group(1), [m.group(2), ""])
            else:
                u = urldefrag(urljoin(self.base, href))[0]
                if u.startswith("http"):
                    self.links.add(u.rstrip("/") if urlparse(u).path not in ("", "/") else u)
                    if DOCEXT_RX.search(urlparse(u).path):
                        self._doc = [u, "", ""]
                        self.docs.setdefault(u, ["", ""])

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "a" and self._doc is not None:
            label = re.sub(r"\s+", " ", self._doc[2]).strip()
            if label and not self.docs[self._doc[0]][1]:
                self.docs[self._doc[0]][1] = label
            self._doc = None
        if tag in SKIP_TAGS and tag != "head":
            self.skip = max(0, self.skip - 1)
            return
        if tag in BLOCK_TAGS:
            self.flush()
        if tag in CHROME_TAGS:
            self.flush()
            self.chrome = max(0, self.chrome - 1)

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.cur.append(data)
            if self._doc is not None:
                self._doc[2] += data


def clean_lines(lines):
    out = []
    for ln in lines:
        if any(rx.search(ln) for rx in IGNORE_RX):
            continue
        out.append(ln)
    return out


def parse_html(url, raw):
    txt = raw.decode("utf-8", "ignore")
    p = Extract(url)
    p.feed(txt)
    p.flush()
    return {
        "title": re.sub(r"\s+", " ", p.title).strip(),
        "desc": p.desc,
        "lines": clean_lines(p.content),
        "chrome": clean_lines(p.chrome_lines),
        "links": sorted(p.links),
        "docs": [[u, v[0], v[1]] for u, v in sorted(p.docs.items())],
    }


def sha(parts):
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


# ----------------------------- SITEMAP -----------------------------
def read_sitemap(url, depth=0):
    """Ritorna lista di (url, lastmod) ricorrendo sugli indici."""
    status, data, _ = http_get(url, accept="application/xml,text/xml,*/*")
    root = ET.fromstring(data)
    out = []
    if root.tag.endswith("sitemapindex"):
        for sm in root.findall("s:sitemap", NS):
            loc = (sm.findtext("s:loc", default="", namespaces=NS) or "").strip()
            if loc and depth < 2:
                out.extend(read_sitemap(loc, depth + 1))
    else:
        for u in root.findall("s:url", NS):
            loc = (u.findtext("s:loc", default="", namespaces=NS) or "").strip()
            lm = (u.findtext("s:lastmod", default="", namespaces=NS) or "").strip()
            if loc:
                out.append((loc, lm))
    return out


def is_page(url):
    return not re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|css|js|xml)$", urlparse(url).path, re.I)


# ----------------------------- SNAPSHOT -----------------------------
def snap_path(url):
    return SNAP / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".json.gz")


def load_snap(url):
    p = snap_path(url)
    if p.exists():
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_snap(url, data):
    SNAP.mkdir(exist_ok=True)
    with gzip.open(snap_path(url), "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def short(s, n=170):
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def diff_text(old, new):
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    rem, add = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            rem.extend(old[i1:i2])
        if tag in ("replace", "insert"):
            add.extend(new[j1:j2])
    return rem, add


DETAIL = {}   # url -> dettagli strutturati dell'ultima variazione (per la pagina web)


def is_trivial(rem, add):
    """Poche righe di una o due parole, senza numeri (es. 'Notify' -> 'Subscribe'): etichette, non contenuti."""
    lines = rem + add
    return bool(lines) and len(rem) <= 3 and len(add) <= 3 and all(len(x.split()) <= 2 and not re.search(r"\d", x) for x in lines)


def describe_change(url, old, new):
    """Ritorna (lista righe descrittive, 'peso' in caratteri) oppure ([], 0) se non rilevante."""
    out, weight = [], 0
    if old["title"] != new["title"]:
        out.append(f"   titolo: «{short(old['title'])}» -> «{short(new['title'])}»")
        weight += len(new["title"])
    if old["desc"] != new["desc"]:
        out.append(f"   descrizione: «{short(old['desc'], 110)}» -> «{short(new['desc'], 110)}»")
        weight += len(new["desc"])
    rem, add = diff_text(old["lines"], new["lines"])
    ch = sum(len(x) for x in rem) + sum(len(x) for x in add)
    if is_trivial(rem, add):   # una parola di un pulsante/etichetta che cambia: non conta
        rem, add, ch = [], [], 0
    if ch >= MIN_CHANGED_CHARS:
        weight += ch
        for ln in rem[:MAX_DIFF_LINES]:
            out.append("   - " + short(ln))
        if len(rem) > MAX_DIFF_LINES:
            out.append(f"   - … altre {len(rem) - MAX_DIFF_LINES} righe tolte")
        for ln in add[:MAX_DIFF_LINES]:
            out.append("   + " + short(ln))
        if len(add) > MAX_DIFF_LINES:
            out.append(f"   + … altre {len(add) - MAX_DIFF_LINES} righe aggiunte")
    ol = {x for x in old["links"] if "blackhole=" not in x}   # trappola anti-bot con codice che cambia a ogni visita
    nl = {x for x in new["links"] if "blackhole=" not in x}
    la, lr = sorted(nl - ol), sorted(ol - nl)
    if la:
        out.append("   link aggiunti: " + ", ".join(short(x, 80) for x in la[:5]) + (f" (+{len(la) - 5})" if len(la) > 5 else ""))
        weight += 20 * len(la)
    if lr:
        out.append("   link tolti: " + ", ".join(short(x, 80) for x in lr[:5]) + (f" (+{len(lr) - 5})" if len(lr) > 5 else ""))
        weight += 20 * len(lr)
    rem2, add2 = diff_text(old["chrome"], new["chrome"])
    chc = sum(len(x) for x in rem2) + sum(len(x) for x in add2)
    if chc >= MIN_CHANGED_CHARS:
        out.append(f"   menu/piè di pagina cambiati ({chc} caratteri)")
        weight += chc // 2
    big = ch >= MIN_CHANGED_CHARS
    DETAIL[url] = {
        "page_title": new["title"] or url,
        "title": [old["title"], new["title"]] if old["title"] != new["title"] else None,
        "desc": [old["desc"], new["desc"]] if old["desc"] != new["desc"] else None,
        "removed": rem[:MAX_DIFF_LINES] if big else [], "n_removed": len(rem) if big else 0,
        "added": add[:MAX_DIFF_LINES] if big else [], "n_added": len(add) if big else 0,
        "links_added": la[:30], "links_removed": lr[:30],
        "chrome": chc if chc >= MIN_CHANGED_CHARS else 0,
    }
    return out, weight


# ----------------------------- DOCUMENTI (PDF / PowerPoint) -----------------------------
def rendered_slug(url):
    return urlparse(url).path.strip("/").replace("/", "_") or "home"


def pptx_text(data):
    import io
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[0]))
        for n in names:
            root = ET.fromstring(z.read(n))
            out.append(" ".join(t.text for t in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if t.text))
    return "\n\f".join(out)


def doc_text(url, data):
    path = urlparse(url).path.lower()
    try:
        if path.endswith(".pdf") and data[:4] == b"%PDF" and shutil.which("pdftotext"):
            p = subprocess.run([shutil.which("pdftotext"), "-layout", "-", "-"], input=data, capture_output=True, timeout=90)
            return p.stdout.decode("utf-8", "ignore") if p.returncode == 0 else None
        if path.endswith(".pptx"):
            return pptx_text(data)
    except Exception as e:  # noqa: BLE001
        log(f"[doc] testo non estratto da {url}: {e}")
    return None


def doc_lines(text):
    return [re.sub(r"\s+", " ", x).strip() for x in (text or "").splitlines() if re.sub(r"[\s\f]+", "", x)]


def doc_txt_path(url):
    return SNAP / ("doc_" + hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt.gz")


def track_docs(sst, docs, page_url, first_run):
    """Scarica i documenti linkati dalla pagina e segnala quelli nuovi o sostituiti (stesso link ma contenuto diverso)."""
    files = sst.setdefault("files", {})
    events, downloaded = [], 0
    for u, h, label in docs:
        rec = files.get(u)
        if rec and rec.get("h") == h:
            continue
        if not first_run and downloaded >= MAX_NEW_FILES_PER_RUN:
            break
        try:
            req = urllib.request.Request(u, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(MAX_FILE_MB * 1024 * 1024 + 1)
        except Exception as e:  # noqa: BLE001
            log(f"[doc] errore download {u}: {e}")
            continue
        downloaded += 1
        time.sleep(1.0)
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            files[u] = {"h": h, "big": True, "label": label}
            continue
        digest = hashlib.sha256(data).hexdigest()
        text = doc_text(u, data)
        lines = doc_lines(text)
        pages = text.count("\f") + (0 if text.rstrip().endswith("\f") else 1) if text and text.strip() else None
        old_lines = []
        if rec and doc_txt_path(u).exists():
            with gzip.open(doc_txt_path(u), "rt", encoding="utf-8") as f:
                old_lines = json.load(f)
        if lines:
            SNAP.mkdir(exist_ok=True)
            with gzip.open(doc_txt_path(u), "wt", encoding="utf-8") as f:
                json.dump(lines, f, ensure_ascii=False)
        files[u] = {"h": h, "sha": digest, "size": len(data), "pages": pages, "label": label or (rec or {}).get("label", ""),
                    "page": page_url}
        if first_run:
            continue
        name = label or u.rsplit("/", 1)[-1]
        kb = f"{len(data) // 1024} KB" + (f", {pages} pagine" if pages else "")
        if rec is None:
            DETAIL[u] = {"page_title": name, "file": {"kind": "new", "size": len(data), "pages": pages, "sha": digest[:12],
                                                     "head": lines[:6], "page": page_url}}
            events.append(("NUOVO FILE", u, [f"   {name} ({kb})", f"   trovato su {page_url}"] + [f"   {x[:120]}" for x in lines[:3]], 3000))
        elif rec.get("sha") and rec.get("sha") != digest:
            rem, add = diff_text(old_lines, lines) if old_lines and lines else ([], [])
            DETAIL[u] = {"page_title": name, "file": {"kind": "changed", "size": len(data), "pages": pages, "sha": digest[:12],
                                                     "old_size": rec.get("size"), "old_pages": rec.get("pages"),
                                                     "removed": rem[:MAX_DIFF_LINES], "added": add[:MAX_DIFF_LINES],
                                                     "n_removed": len(rem), "n_added": len(add), "page": page_url}}
            events.append(("FILE MODIFICATO", u, [f"   {name}: ora {kb} (prima {(rec.get('size') or 0) // 1024} KB)"]
                           + [f"   - {short(x)}" for x in rem[:4]] + [f"   + {short(x)}" for x in add[:4]], 4000))
    return events


# ----------------------------- CONTROLLO DI UNA FONTE -----------------------------
def check_source(src, st, now):
    name = src["name"]
    sst = st["sources"].setdefault(name, {"pages": {}, "ready": False})
    pages = sst["pages"]
    items = []
    if "sitemap_index" in src:
        items = [(u, lm) for u, lm in read_sitemap(src["sitemap_index"]) if is_page(u)]
    for u in src.get("pages", []):
        items.append((u, ""))
    seen = {}
    for u, lm in items:
        if any(p in u for p in SKIP_URL_PATTERNS):
            pages.pop(u, None)
            continue
        seen[u] = lm
    urls = list(seen)[:MAX_PAGES_PER_SOURCE]
    first_run = not sst["ready"]
    events = []      # (tipo, url, righe descrittive, peso)
    fetched = 0
    for u in urls:
        meta = pages.get(u)
        lm = seen[u]
        due = (meta is None or meta.get("lastmod") != lm or "pages" in src and u in src["pages"]
               or now - meta.get("checked", 0) > FULL_CHECK_EVERY_HOURS * 3600)
        if not due:
            continue
        if src.get("rendered_dir"):   # pagina gia' caricata da un browser vero (render.py); se manca la salto
            rf = HERE / src["rendered_dir"] / (rendered_slug(u) + ".html")
            if not rf.exists():
                log(f"[{name}] pagina non scaricata dal browser, salto: {u}")
                continue
            status, raw, hdr = 200, rf.read_bytes(), {}
        else:
            try:
                status, raw, hdr = http_get(u, etag=(meta or {}).get("etag"), last_mod=(meta or {}).get("lm"),
                                            accept="text/html,*/*")
            except Exception as e:  # noqa: BLE001
                log(f"[{name}] errore lettura {u}: {e}")
                continue
            time.sleep(src.get("delay", 1.0))
        fetched += 1
        if status == 304:
            meta["checked"] = now
            meta["lastmod"] = lm
            continue
        new = parse_html(u, raw)
        new["fetched"] = datetime.now().isoformat(timespec="seconds")
        old = load_snap(u) if meta else None
        if (src.get("rendered_dir") and old and len(old["lines"]) >= 6
                and len(new["lines"]) < SHRINK_RATIO * len(old["lines"]) and meta.get("pending", 0) < SHRINK_CONFIRM):
            # pagina IR che di colpo perde piu' di meta' del testo: quasi sempre il widget non ha caricato l'elenco.
            # Non tocco la versione salvata; se resta cosi' per SHRINK_CONFIRM controlli di fila (~4 giorni), allora e' vero.
            meta["pending"] = meta.get("pending", 0) + 1
            meta["checked"] = now - FULL_CHECK_EVERY_HOURS * 3600 + 600
            log(f"[{name}] pagina molto piu' corta ({len(old['lines'])} -> {len(new['lines'])} righe), attendo conferma ({meta["pending"]}/{SHRINK_CONFIRM}): {u}")
            continue
        pages[u] = {"lastmod": lm, "checked": now, "etag": hdr.get("ETag"), "lm": hdr.get("Last-Modified"),
                    "hash": sha(new["lines"]), "title": new["title"]}
        save_snap(u, new)
        if src.get("track_docs") and "press-releases" not in u:
            events.extend(track_docs(sst, new.get("docs", []), u, first_run))
        if first_run:
            continue
        if old is None:
            DETAIL[u] = {"page_title": new["title"] or u, "chars": len(" ".join(new["lines"]))}
            events.append(("NUOVA PAGINA", u, [f"   titolo: «{short(new['title'])}»", f"   {len(' '.join(new['lines']))} caratteri di testo"], 1000))
            continue
        lines, weight = describe_change(u, old, new)
        if lines:
            events.append(("PAGINA MODIFICATA", u, lines, weight))
        elif meta and meta.get("lastmod") != lm:
            log(f"[{name}] solo data cambiata, contenuto uguale: {u}")
    # pagine sparite
    if not first_run:
        for u in list(pages):
            if u not in seen and "sitemap_index" in src:
                events.append(("PAGINA RIMOSSA", u, ["   (non e' piu' nella sitemap)"], 1000))
                del pages[u]
    if fetched or not first_run:   # se al primo giro non ho potuto leggere nulla (es. browser non partito) la base non e' pronta
        sst["ready"] = True
    sst["count"] = len(urls)
    if first_run:
        log(f"[{name}] base creata: {len(urls)} pagine (nessun avviso)")
    else:
        log(f"[{name}] controllate {fetched} pagine su {len(urls)}; variazioni: {len(events)}")
    return events, first_run, len(urls)


# ----------------------------- EDGAR (opzionale) -----------------------------
def check_edgar(st):
    if not EDGAR_UA:
        return []
    sst = st["sources"].setdefault("EDGAR", {"seen": [], "ready": False})
    cik = sst.get("cik") or EDGAR_CIK
    if not cik:   # risolvo il CIK dal ticker e controllo che sia davvero Gorilla
        _, data, _ = http_get("https://www.sec.gov/files/company_tickers.json", ua=EDGAR_UA)
        hit = [c for c in json.loads(data).values() if c.get("ticker", "").upper() == EDGAR_TICKER]
        if not hit or EDGAR_NAME_CHECK not in hit[0].get("title", "").lower():
            raise RuntimeError(f"EDGAR: ticker {EDGAR_TICKER} non corrisponde a {EDGAR_NAME_CHECK}: {hit}")
        cik = f"{int(hit[0]['cik_str']):010d}"
        sst["cik"] = cik
        log(f"[EDGAR] CIK risolto: {cik} ({hit[0]['title']})")
    status, data, _ = http_get(f"https://data.sec.gov/submissions/CIK{cik}.json", ua=EDGAR_UA)
    rec = json.loads(data)["filings"]["recent"]

    def col(name, i):
        v = rec.get(name) or []
        return v[i] if i < len(v) else ""

    cur = []
    for i, acc in enumerate(rec["accessionNumber"][:60]):
        cur.append({"acc": acc, "form": rec["form"][i], "date": rec["filingDate"][i], "doc": rec["primaryDocument"][i],
                    "desc": col("primaryDocDescription", i), "items": col("items", i)})
    events = []
    if sst["ready"]:
        known = set(sst["seen"])
        for f in cur:
            if f["acc"] in known or not (EDGAR_FORMS_OF_INTEREST is None or f["form"] in EDGAR_FORMS_OF_INTEREST):
                continue
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{f['acc'].replace('-', '')}"
            url = f"{base}/{f['doc']}"
            docs = []
            try:   # elenco degli allegati (comunicato, presentazione...) con i link diretti
                _, idx, _ = http_get(f"{base}/index.json", ua=EDGAR_UA)
                for it in json.loads(idx)["directory"]["item"]:
                    if it["name"].lower().endswith((".htm", ".html", ".pdf", ".pptx", ".ppt", ".xml", ".txt")) and "index" not in it["name"].lower():
                        docs.append({"name": it["name"], "url": f"{base}/{it['name']}"})
            except Exception as e:  # noqa: BLE001
                log(f"[EDGAR] indice non letto per {f['acc']}: {e}")
            time.sleep(0.3)
            DETAIL[url] = {"page_title": f"{f['form']}: {f['desc'] or f['items'] or f['doc']}",
                           "sec": {"form": f["form"], "date": f["date"], "items": f["items"], "desc": f["desc"],
                                   "acc": f["acc"], "index": f"{base}/{f['acc']}-index.htm", "docs": docs[:20]}}
            lines = [f"   {f['form']} del {f['date']} {f['desc']}".rstrip()]
            if f["items"]:
                lines.append(f"   punti (items): {f['items']}")
            lines += [f"   allegato: {d['url']}" for d in docs[:8]]
            events.append(("NUOVO DOCUMENTO SEC", url, lines, 5000))
    sst["seen"] = [f["acc"] for f in cur]
    sst["ready"] = True
    return events


# ----------------------------- MAIN -----------------------------
def main() -> int:
    st = json.loads(STATE.read_text(encoding="utf-8-sig")) if STATE.exists() else {"sources": {}, "fails": {}}
    now = time.time()
    all_events = []
    tasks = [(s["name"], lambda s=s: check_source(s, st, now)) for s in SOURCES]
    for name, fn in tasks:
        try:
            events, first, n = fn()
            st["fails"][name] = 0
        except Exception as e:  # noqa: BLE001
            st["fails"][name] = st["fails"].get(name, 0) + 1
            log(f"[{name}] ERRORE: {e}")
            if st["fails"][name] == FAILS_BEFORE_ALERT:
                all_events.append((name, [("PROBLEMA", name, [f"   fonte non raggiungibile da {FAILS_BEFORE_ALERT} controlli di fila"], 9999)]))
            continue
        npage = sum(1 for e in events if e[0] in ("PAGINA MODIFICATA", "NUOVA PAGINA", "PAGINA RIMOSSA"))
        if not first and n and npage >= max(5, MASS_CHANGE_RATIO * n):
            head = [f"   {npage} pagine su {n} cambiate nello stesso controllo: probabile cambio di tema, "
                    f"manutenzione o aggiornamento di plugin. Primi esempi:"]
            for typ, u, lines, w in events[:3]:
                head.append(f"   {typ}: {u}")
                head.extend(lines[:4])
            events = [("CAMBIO DI MASSA", name, head, 9999)]
        if events:
            all_events.append((name, events))
    try:
        ev = check_edgar(st)
        if ev:
            all_events.append(("EDGAR Gorilla", ev))
    except Exception as e:  # noqa: BLE001
        log(f"[EDGAR] ERRORE: {e}")

    if all_events:
        stamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        body = []
        total = 0
        for name, events in all_events:
            body.append(f"[{name}]")
            for typ, u, lines, w in sorted(events, key=lambda e: -e[3]):
                body.append(f"  {typ}: {u}")
                body.extend(lines)
                total += 1
            body.append("")
        text = "\n".join(body).rstrip()
        with ALERTS.open("a", encoding="utf-8") as f:
            f.write(f"=== {stamp} ===\n{text}\n")
        LAST_ALERT.write_text(f"{stamp}\n{text}\n", encoding="utf-8")
        log(f"AVVISO: {total} variazioni\n{text}")
        hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
        iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for name, events in all_events:
            for typ, u, lines, w in sorted(events, key=lambda e: -e[3]):
                hist.append({"ts": iso, "source": name, "type": typ, "url": u,
                             "text": [x.strip() for x in lines], "detail": DETAIL.get(u)})
        HISTORY.write_text(json.dumps(hist[-400:], ensure_ascii=False, indent=1), encoding="utf-8")
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
