"""KAP Portföy Dağılım Raporu: fonların hisse bazında yoğunlaşması.

TEFAS yalnızca varlık sınıfı dağılımı verir; hangi hisselerin ne kadar tutulduğu, fonların KAP'a her ay
(serbest fonlarda her hafta) gönderdiği "Portföy Dağılım Raporu" PDF ekindedir. Bu modül:

  1. KAP'ın herkese açık fon bildirimi sorgusundan son günlerin raporlarını listeler,
  2. her fonun en yeni raporunu (daha önce işlenmediyse) indirir, PDF metnini çıkarır,
  3. "HİSSE SENETLERİ" bölümündeki satırlardan hisse sayısı, en büyük hisse payı ve ilk 3 / 5 hisse
     toplamını (fon portföy değerine göre, FPD %) hesaplayıp kap_portfolio tablosuna yazar.

Her çalıştırma bir zaman bütçesiyle sınırlıdır; işlenemeyenler sonraki gün devam eder.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request

BASE = "https://www.kap.org.tr/tr/api"
UA = {"User-Agent": "Mozilla/5.0 (TEFAS Quant; portfoy dagilim raporu)"}
SUBJECT = "Portföy Dağılım Raporu"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kap_portfolio (
    code TEXT PRIMARY KEY,
    disclosure_index INTEGER,
    period TEXT,
    publish_date TEXT,
    n_stocks INTEGER,
    equity REAL,
    max_w REAL,
    top3 REAL,
    top5 REAL,
    top_name TEXT,
    coverage REAL,
    checked_at TEXT
);
"""

NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+"
TAIL = re.compile(rf"({NUM})\s+({NUM})\s+({NUM})\s+({NUM})\s*$")  # toplam değer, grup %, FPD %, FTD %
ISIN = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
# Bölüm başlıkları (satırın tamamı). Sayfa başlarında tekrarlanan sütun başlıkları ("DÖVİZ", "CİNSİ"…) bölüm sayılmaz.
END_HEADERS = {"BORÇLANMA SENETLERİ", "T.REPO", "T. REPO", "REPO", "DİĞER", "TÜREV", "TÜREV ARAÇLAR", "KATILIM HESABI",
               "MEVDUAT", "VADELİ MEVDUAT", "YATIRIM FONLARI", "YATIRIM FONU", "FON PAYLARI", "KİRA SERTİFİKALARI",
               "KIYMETLİ MADENLER", "VARANT", "OPSİYON", "TPP", "BORSA YATIRIM FONLARI", "GAYRİMENKUL SERTİFİKALARI",
               "VİOP", "VIOP"}
DEBT_ISIN = ("TRT", "TRS", "TRD", "TRF")  # devlet / özel sektör borçlanma araçları
TICKER = re.compile(r"^([A-Z0-9]{3,6})(?= [A-ZÇĞİÖŞÜ])")  # "AHGAZ AHLATCI…", "AAPL US EQUITY…"


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


CURRENCIES = {"TL", "TRY", "USD", "EUR", "CHF", "GBP", "JPY", "CAD", "AUD", "SEK", "NOK", "DKK", "CNY", "HKD"}
DATE = re.compile(r"\b\d{2}/\d{2}/\d{2,4}\b")
GROUP_TOTAL = re.compile(rf"^GRUP TOPLAMI\b.*?({NUM})\s+({NUM})\s+({NUM})\s*$")


def _equity_section(lines: list[str]):
    """HİSSE SENETLERİ bölümünün satırları (sıra numarasıyla). PDF metninde sayfa düzeni yüzünden bölümün arasına
    başka tablolar (IV-Fon Toplam Değeri, V-Giderler) girebilir; bölüm yalnızca bir sonraki varlık bölümüyle
    ya da VI ve sonrası başlıklarla biter."""
    on = False
    for i, line in enumerate(lines):
        if re.fullmatch(r"H[İI]SSE SENETLER[İI]", line, re.I):
            on = True
            continue
        if on and (line in END_HEADERS or re.match(r"^(VI|VII|VIII|IX|X)[-.]", line)):
            on = False
        if on:
            yield i, line


def holdings(text: str) -> tuple[list[tuple[str, str, float]], float | None]:
    """([(anahtar, ad, FPD %)], raporun kendi hisse toplamı FPD %). Satır: alış tarihi + sonda 4 sayı."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, totals = [], []
    for i, line in _equity_section(lines):
        if line.upper().startswith("GRUP TOPLAMI"):
            g = GROUP_TOTAL.match(line)
            if g:
                totals.append(_num(g.group(2)))
            continue
        m = TAIL.search(line)
        if not m or not DATE.search(line) or "TOPLAM" in line.upper():
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        isin = ISIN.search(line) or (ISIN.fullmatch(nxt) and ISIN.match(nxt))
        if isin and isin.group(1)[:3] in DEBT_ISIN:
            continue
        before = lines[max(0, i - 8): i]
        name = next((t.group(1) for t in (TICKER.match(x) for x in [line, *reversed(before)])
                     if t and t.group(1) not in CURRENCIES and not t.group(1).isdigit()), None)
        key = isin.group(1) if isin else (name or line[:20])
        out.append((key, name or key, _num(m.group(3))))
    # Bölümün kendi toplamı: en büyük GRUP TOPLAMI (alt grup + bölüm toplamı tekrarlanır)
    return out, (max(totals) if totals else None)


def has_table(text: str) -> bool:
    """Raporda portföy değeri tablosu var mı? Bazı haftalık serbest fon raporları yalnızca alım / satımları içerir."""
    up = text.upper()
    return "PORTFÖY DEĞERİ TABLOSU" in up or "FON PORTFÖY DEĞERİ" in up


def metrics(text: str) -> dict | None:
    """Hisse yoğunlaşması; raporda portföy tablosu yoksa None (bilinmiyor; 0 hisse sayılmaz).
    Aynı hisse farklı alış günleri için ayrı satırlarda olabilir: ISIN'e göre toplanır. coverage: okunan satırların
    raporun kendi hisse toplamına oranı (1'e yakın olmalı; düşükse ayrıştırma eksik)."""
    if not has_table(text):
        return None
    rows, total = holdings(text)
    agg: dict[str, list] = {}
    for key, name, x in rows:
        a = agg.setdefault(key, [name, 0.0])
        a[1] += x
    h = sorted(((n, round(x, 2)) for n, x in agg.values()), key=lambda t: -t[1])
    w = [x for _, x in h]
    parsed = round(sum(w), 2)
    equity = total if total is not None else parsed
    coverage = round(parsed / equity, 3) if equity else (1.0 if not w else None)
    return {"n_stocks": len(w), "equity": round(equity, 2), "max_w": w[0] if w else 0.0, "top3": round(sum(w[:3]), 2),
            "top5": round(sum(w[:5]), 2), "top_name": h[0][0] if h else None, "coverage": coverage}


# ------------------------------------------------------------------ KAP istekleri
def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**UA, "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


class RateLimited(Exception):
    """KAP istek sınırı (HTTP 429) bekledikten sonra da sürüyor: bu çalıştırma durur, sonraki gün devam eder."""


def _get(url: str, retries: int = 2, backoff: float = 90.0) -> bytes:
    for k in range(retries + 1):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            if k == retries:
                raise RateLimited(url) from e
            time.sleep(backoff * (k + 1))


def list_reports(days: int = 45, end: dt.date | None = None, chunk_days: int = 2, delay: float = 2.0) -> dict[str, dict]:
    """Son `days` günün Portföy Dağılım Raporları: fon kodu -> en yeni bildirim. (Sorgu en fazla 2000 kayıt döndürür.)"""
    end = end or dt.date.today()
    start = end - dt.timedelta(days=days)
    latest: dict[str, dict] = {}
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=chunk_days - 1))
        rows = _post(f"{BASE}/disclosure/funds/byCriteria",
                     {"fromDate": d.isoformat(), "toDate": e.isoformat(), "fundTypeList": ["YF"], "subjectList": []})
        if len(rows) >= 2000 and chunk_days > 1:  # sınıra takıldı: bu aralığı gün gün sorgula
            for k in range(chunk_days):
                day = d + dt.timedelta(days=k)
                if day <= e:
                    rows += _post(f"{BASE}/disclosure/funds/byCriteria",
                                  {"fromDate": day.isoformat(), "toDate": day.isoformat(), "fundTypeList": ["YF"], "subjectList": []})
                    time.sleep(delay)
        for r in rows:
            if (r.get("subject") or "").strip() != SUBJECT or not r.get("fundCode") or not r.get("attachmentCount"):
                continue
            code = r["fundCode"].strip().upper()
            if code not in latest or r["disclosureIndex"] > latest[code]["disclosureIndex"]:
                latest[code] = r
        d = e + dt.timedelta(days=1)
        time.sleep(delay)
    return latest


def report_text(disclosure_index: int) -> str:
    """Bildirimin PDF ekinin metni. Dosya Java bayt dizisi sarmalayıcısında gelir; %PDF'den itibaren kesilir."""
    import pypdfium2 as pdfium

    detail = json.loads(_get(f"{BASE}/notification/attachment-detail/{disclosure_index}"))[0]
    att = [a for a in (detail.get("attachments") or []) if str(a.get("fileExtension", "")).lower() == "pdf"]
    if not att:
        raise ValueError("PDF eki yok")
    raw = _get(f"{BASE}/file/download/{att[0]['objId']}")
    i = raw.find(b"%PDF")
    if i < 0:
        raise ValueError("PDF değil")
    doc = pdfium.PdfDocument(raw[i:])
    try:
        return "\n".join(doc[k].get_textpage().get_text_range() for k in range(len(doc)))
    finally:
        doc.close()


def update(conn: sqlite3.Connection, codes: list[str] | None = None, days: int = 45, delay: float = 4.0,
           budget_min: float = 10.0, log=print) -> dict:
    """Yeni raporları işler. codes verilirse yalnızca o fonlar, verilen sırayla (önce önerilebilir fonlar).
    KAP sık isteği 429 ile keser: raporlar arasında `delay` saniye beklenir, sınır sürerse çalıştırma durur."""
    conn.executescript(SCHEMA)
    if "coverage" not in {r[1] for r in conn.execute("PRAGMA table_info(kap_portfolio)")}:
        conn.execute("ALTER TABLE kap_portfolio ADD COLUMN coverage REAL")
    t0 = time.time()
    latest = list_reports(days=days, delay=delay)
    known = dict(conn.execute("SELECT code, disclosure_index FROM kap_portfolio").fetchall())
    order = {c: i for i, c in enumerate(codes)} if codes is not None else None
    todo = [r for c, r in latest.items() if (order is None or c in order) and known.get(c) != r["disclosureIndex"]]
    # önce hiç işlenmemiş fonlar, sonra verilen öncelik sırası
    todo.sort(key=lambda r: (r["fundCode"] in known, order.get(r["fundCode"], 1e9) if order else -r["disclosureIndex"]))
    done = failed = 0
    for r in todo:
        if time.time() - t0 > budget_min * 60:
            break
        code = r["fundCode"].strip().upper()
        try:
            m = metrics(report_text(r["disclosureIndex"])) or dict.fromkeys(("n_stocks", "equity", "max_w", "top3", "top5", "top_name", "coverage"))
            conn.execute(
                "INSERT OR REPLACE INTO kap_portfolio (code, disclosure_index, period, publish_date, n_stocks, equity, max_w, top3, top5, top_name, coverage, checked_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, r["disclosureIndex"], r.get("ruleType"), r.get("publishDate"), m["n_stocks"], m["equity"], m["max_w"],
                 m["top3"], m["top5"], m["top_name"], m["coverage"], dt.datetime.now().isoformat(timespec="seconds")))
            done += 1
            if done % 50 == 0:
                conn.commit()
                log(f"  [kap] {done} rapor işlendi")
        except RateLimited:
            log("  [kap] istek sınırı sürüyor; tarama sonraki çalıştırmada devam edecek")
            break
        except Exception as e:  # noqa: BLE001 - tek rapor hatası taramayı durdurmasın
            failed += 1
            log(f"  [kap] {code} {r['disclosureIndex']}: {e}")
        time.sleep(delay)
    conn.commit()
    left = len(todo) - done - failed
    log(f"[kap] {len(latest)} fonun raporu listelendi · {done} yeni işlendi · {failed} hata · {left} sonraki çalıştırmaya")
    return {"listed": len(latest), "done": done, "failed": failed, "left": left}


def recent(conn: sqlite3.Connection, max_age_days: int = 75):
    """Yayın tarihi max_age_days'ten yeni raporlar (eski rapor yoğunlaşma kararında kullanılmaz)."""
    import pandas as pd

    df = load(conn)
    if not len(df):
        return df
    pub = pd.to_datetime(df["publish_date"], format="%d.%m.%Y %H:%M:%S", errors="coerce")
    return df[pub >= pd.Timestamp.now() - pd.Timedelta(days=max_age_days)]


def load(conn: sqlite3.Connection):
    """kap_portfolio tablosu (yoksa boş)."""
    import pandas as pd

    try:
        return pd.read_sql("SELECT * FROM kap_portfolio", conn).set_index("code")
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["n_stocks", "equity", "max_w", "top3", "top5", "top_name", "period", "publish_date"])
