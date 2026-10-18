"""TEFAS ve FVT'den veri çekme, kategori eşleme ve 5 yıllık budama."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .db import meta_get, meta_set
from .tefas import Tefas

KIND = "YAT"  # TEFAS Quant yatırım fonlarını sıralar


CHUNK_DAYS = 28  # TEFAS tek istekte ~1 ay döndürüyor


def fetch_window(conn: sqlite3.Connection, client: Tefas, start: dt.date, end: dt.date) -> int:
    """Tek bir ≤28 günlük pencerenin tüm YAT fon kayıtlarını yazar ve hemen kaydeder.

    Her pencereden sonra commit edildiği için iş yarıda kesilse de (zaman aşımı,
    hız sınırı) o ana kadar çekilenler kaybolmaz; cache'e kaydedilip sonraki
    çalışmada kalınan yerden devam edilir.
    """
    rows, names = [], {}
    for rec in client.prices(KIND, start, end):
        rows.append((rec["date"], rec["code"], rec["price"], rec["shares"], rec["investors"], rec["size"]))
        names[rec["code"]] = rec["name"]
    conn.executemany(
        "INSERT OR REPLACE INTO prices (date, code, price, shares, investors, size)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO funds (code, name) VALUES (?, ?)"
        " ON CONFLICT(code) DO UPDATE SET name = excluded.name",
        list(names.items()),
    )
    conn.commit()
    return len(rows)


def _windows(start: dt.date, end: dt.date, newest_first: bool):
    spans, cur = [], start
    while cur <= end:
        stop = min(cur + dt.timedelta(days=CHUNK_DAYS - 1), end)
        spans.append((cur, stop))
        cur = stop + dt.timedelta(days=1)
    return reversed(spans) if newest_first else spans


def sync_categories(conn: sqlite3.Connection, client: Tefas, end: dt.date, force: bool = False) -> int:
    """TEFAS'ın resmî şemsiye fon türlerini fonlara eşler (haftada bir)."""
    # Resmî listede olmayan fonların kategorisi ünvandan çıkarılır (categorize),
    # bu yüzden boş kategori tek başına yeniden eşleme sebebi değildir.
    last = meta_get(conn, "category_sync")
    if (not force and last
            and (end - dt.date.fromisoformat(last)).days < config.CATEGORY_REFRESH_DAYS):
        print("[kategori] yakın zamanda eşlendi, atlanıyor", flush=True)
        return 0

    try:
        types = client.fund_types(KIND)
        all_codes = client.codes_for_type(KIND, None, end)
    except Exception as exc:  # TEFAS geçici hatası skorlamayı durdurmasın
        print(f"[kategori] hata: {exc}", flush=True)
        return 0

    matched = {}
    for t in types:
        code, name = t.get("sfonTuru"), (t.get("sfonTurAciklama") or "").strip()
        if not code or not name:
            continue
        try:
            codes = client.codes_for_type(KIND, code, end)
        except Exception:
            continue
        # Filtre çalışmazsa API tüm fonları döndürür; o türü yok say.
        if codes and codes != all_codes:
            label = name.replace(" Şemsiye Fonu", "").strip()
            for c in codes:
                matched[c] = label

    if matched:
        conn.executemany(
            "UPDATE funds SET category = ?, category_src = 'tefas' WHERE code = ?",
            [(label, c) for c, label in matched.items()],
        )
        conn.commit()
        meta_set(conn, "category_sync", end.isoformat())
    print(f"[kategori] {len(matched)} fon eşlendi", flush=True)
    return len(matched)


# ------------------------------------------------------------------- FVT

FVT_URL = "https://fvt.com.tr/api/funds/{code}"
# FVT'nin depoya giren küçük kopyası. GitHub Actions sunucularından FVT'ye
# ulaşılamayabiliyor; o durumda ücret/stopaj/işlem durumu buradan gelir.
FVT_SNAPSHOT = Path(__file__).resolve().parent / "fund_info.json"
FVT_FIELDS = ("fee", "stopaj", "trading_active", "is_serbest", "fvt_updated")


def save_fvt_snapshot(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        f"SELECT code, {', '.join(FVT_FIELDS)} FROM funds WHERE fvt_updated IS NOT NULL ORDER BY code"
    ).fetchall()
    data = {r[0]: dict(zip(FVT_FIELDS, r[1:])) for r in rows}
    FVT_SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(data)


def load_fvt_snapshot(conn: sqlite3.Connection) -> int:
    """Depodaki kopyayı, FVT bilgisi olmayan fonlara uygular."""
    if not FVT_SNAPSHOT.exists():
        return 0
    data = json.loads(FVT_SNAPSHOT.read_text(encoding="utf-8"))
    cur = conn.executemany(
        f"UPDATE funds SET {', '.join(f'{k} = ?' for k in FVT_FIELDS)} WHERE code = ? AND fvt_updated IS NULL",
        [tuple(v.get(k) for k in FVT_FIELDS) + (code,) for code, v in data.items()],
    )
    conn.commit()
    return cur.rowcount


def _fvt_fund(code: str) -> dict | None:
    req = urllib.request.Request(
        FVT_URL.format(code=code),
        headers={"Accept": "application/json", "User-Agent": "tefas-quant/1.0"},
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return (data.get("data") or {}).get("fund") or None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            pass
        time.sleep(1.0 + attempt)
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sync_fvt(conn: sqlite3.Connection, end: dt.date, force: bool = False,
             workers: int = 6, budget_s: float = 180) -> int:
    """Yönetim ücreti, stopaj, TEFAS işlem durumu ve serbest fon bayrağı (haftada bir).

    Fiyat, yatırımcı ve büyüklük TEFAS'tan geldiği için FVT yalnızca bu
    seyrek değişen alanlar için kullanılır. Hata olursa eski değerler kalır.
    Süre bütçesi ve devre kesici var: FVT yavaşsa ya da yanıt vermiyorsa
    derlemeyi bekletmeden bırakılır, kalanlar sonraki çalışmada denenir.
    """
    last = meta_get(conn, "fvt_sync")
    if not force and last and (end - dt.date.fromisoformat(last)).days < config.FVT_REFRESH_DAYS:
        print("[fvt] yakın zamanda güncellendi, atlanıyor", flush=True)
        return 0

    # Son 60 günde fiyatı olan fonlar (yeni askıya alınanlar da dahil);
    # en uzun süredir güncellenmeyenler önce.
    since = (end - dt.timedelta(days=60)).isoformat()
    codes = [r[0] for r in conn.execute(
        "SELECT p.code FROM (SELECT DISTINCT code FROM prices WHERE date >= ?) p"
        " LEFT JOIN funds f ON f.code = p.code ORDER BY f.fvt_updated IS NOT NULL, f.fvt_updated",
        (since,),
    )]
    updated = failed = 0
    deadline = time.monotonic() + budget_s
    now = dt.datetime.now().isoformat(timespec="seconds")
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(_fvt_fund, c): c for c in codes}
    try:
        for fut in as_completed(futures):
            fund = fut.result()
            if not fund:
                failed += 1
                # Devre kesici: ilk 40 denemenin hepsi başarısızsa FVT erişilemez say
                if updated == 0 and failed >= 40:
                    print("[fvt] erişilemiyor, bu çalışmada atlanıyor", flush=True)
                    break
                continue
            if time.monotonic() > deadline:
                print("[fvt] süre bütçesi doldu, kalanlar sonraki çalışmada", flush=True)
                break
            conn.execute(
                "UPDATE funds SET fee = ?, stopaj = ?, trading_active = ?, is_serbest = ?,"
                " fvt_updated = ? WHERE code = ?",
                (
                    _num(fund.get("yonetimUcret")),
                    _num(fund.get("stopaj")),
                    int(fund["islem"]) if fund.get("islem") is not None else None,
                    int(fund["serbest"]) if fund.get("serbest") is not None else None,
                    now,
                    futures[fut],
                ),
            )
            updated += 1
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    conn.commit()
    # Fonların çoğu güncellendiyse haftalık tur tamam sayılır ve kopya yenilenir
    if codes and updated >= len(codes) * 0.8:
        meta_set(conn, "fvt_sync", end.isoformat())
        print(f"[fvt] depo kopyası yenilendi: {save_fvt_snapshot(conn)} fon", flush=True)
    print(f"[fvt] {updated}/{len(codes)} fon güncellendi", flush=True)
    filled = load_fvt_snapshot(conn)
    if filled:
        print(f"[fvt] {filled} fon için bilgi depo kopyasından alındı", flush=True)
    return updated


def prune(conn: sqlite3.Connection, today: dt.date) -> int:
    """HISTORY_YEARS yıldan eski fiyatları ve skor fotoğraflarını siler."""
    cutoff = today - dt.timedelta(days=config.HISTORY_YEARS * 365 + config.RETENTION_BUFFER_DAYS)
    removed = conn.execute("DELETE FROM prices WHERE date < ?", (cutoff.isoformat(),)).rowcount
    conn.execute("DELETE FROM scores WHERE date < ?", (cutoff.isoformat(),))
    conn.commit()
    print(f"[budama] {cutoff} öncesi {removed} fiyat satırı silindi", flush=True)
    return removed


def update(conn: sqlite3.Connection, delay: float = 3.0, full: bool = False,
           budget_min: float | None = None) -> None:
    """Önce güncel günleri, sonra eksik geçmişi (yeniden eskiye) çeker.

    budget_min verilirse geçmiş doldurma bu süre dolunca durur; site yine de
    güncel fiyatla yayınlanır, kalan geçmiş sonraki çalışmalarda tamamlanır.
    İlk kurulumda geçmiş tek seferde değil, birkaç çalışmaya yayılarak dolar.
    """
    started = time.monotonic()
    out_of_time = lambda: budget_min is not None and time.monotonic() - started > budget_min * 60  # noqa: E731

    today = dt.date.today()
    cutoff = today - dt.timedelta(days=config.HISTORY_YEARS * 365 + config.RETENTION_BUFFER_DAYS)
    if full:
        conn.execute("DELETE FROM prices")
        conn.commit()
    lo, hi = conn.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
    client = Tefas(delay=delay)

    # 1) Güncel: son kayıttan (ya da boşsa son 4 haftadan) bugüne
    recent_start = (
        max(dt.date.fromisoformat(hi) - dt.timedelta(days=config.OVERLAP_DAYS), cutoff)
        if hi else today - dt.timedelta(days=CHUNK_DAYS * 4)  # skor için ≥60 işlem günü
    )
    for s, e in _windows(recent_start, today, newest_first=False):
        n = fetch_window(conn, client, s, e)
        print(f"[fiyat] {s} -> {e}: {n} kayıt", flush=True)

    # 2) Geçmiş doldurma: en eski kayıttan geriye, 3 yıllık pencerenin başına kadar (HISTORY_YEARS)
    lo = conn.execute("SELECT MIN(date) FROM prices").fetchone()[0]
    oldest = dt.date.fromisoformat(lo) if lo else recent_start
    if oldest > cutoff + dt.timedelta(days=7):
        for s, e in _windows(cutoff, oldest - dt.timedelta(days=1), newest_first=True):
            if out_of_time():
                print(f"[geçmiş] süre bütçesi doldu; {e} öncesi sonraki çalışmada", flush=True)
                break
            n = fetch_window(conn, client, s, e)
            print(f"[geçmiş] {s} -> {e}: {n} kayıt", flush=True)
    else:
        print("[geçmiş] saklama penceresi tamam", flush=True)

    sync_categories(conn, client, today, force=full)
    sync_fvt(conn, today, force=full)
    prune(conn, today)
