"""TEFAS ve FVT'den veri çekme, kategori eşleme ve 3 yıllık budama."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .db import meta_get, meta_set
from .tefas import Tefas

KIND = "YAT"  # TEFAS Quant yatırım fonlarını sıralar


def fetch_prices(conn: sqlite3.Connection, client: Tefas, start: dt.date, end: dt.date) -> int:
    """Tüm YAT fonlarının günlük fiyat, pay, yatırımcı ve büyüklük kayıtları."""
    print(f"[fiyat] {start} -> {end}", flush=True)
    rows, names, total = [], {}, 0

    def flush():
        nonlocal total
        conn.executemany(
            "INSERT OR REPLACE INTO prices (date, code, price, shares, investors, size)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        total += len(rows)
        rows.clear()

    for rec in client.prices(KIND, start, end):
        rows.append((rec["date"], rec["code"], rec["price"], rec["shares"], rec["investors"], rec["size"]))
        names[rec["code"]] = rec["name"]
        if len(rows) >= 50_000:
            flush()
    if rows:
        flush()

    conn.executemany(
        "INSERT INTO funds (code, name) VALUES (?, ?)"
        " ON CONFLICT(code) DO UPDATE SET name = excluded.name",
        list(names.items()),
    )
    conn.commit()
    return total


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


def _fvt_fund(code: str) -> dict | None:
    req = urllib.request.Request(
        FVT_URL.format(code=code),
        headers={"Accept": "application/json", "User-Agent": "tefas-quant/1.0"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return (data.get("data") or {}).get("fund") or None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sync_fvt(conn: sqlite3.Connection, end: dt.date, force: bool = False, workers: int = 4) -> int:
    """Yönetim ücreti, stopaj, TEFAS işlem durumu ve serbest fon bayrağı (haftada bir).

    Fiyat, yatırımcı ve büyüklük TEFAS'tan geldiği için FVT yalnızca bu
    seyrek değişen alanlar için kullanılır. Hata olursa eski değerler kalır.
    """
    last = meta_get(conn, "fvt_sync")
    if not force and last and (end - dt.date.fromisoformat(last)).days < config.FVT_REFRESH_DAYS:
        print("[fvt] yakın zamanda güncellendi, atlanıyor", flush=True)
        return 0

    # Son 60 günde fiyatı olan fonlar
    since = (end - dt.timedelta(days=60)).isoformat()  # yeni askıya alınanlar da dahil
    codes = [r[0] for r in conn.execute("SELECT DISTINCT code FROM prices WHERE date >= ?", (since,))]
    updated = 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fvt_fund, c): c for c in codes}
        for fut in as_completed(futures):
            fund = fut.result()
            if not fund:
                continue
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
    conn.commit()
    if updated:
        meta_set(conn, "fvt_sync", end.isoformat())
    print(f"[fvt] {updated}/{len(codes)} fon güncellendi", flush=True)
    return updated


def prune(conn: sqlite3.Connection, today: dt.date) -> int:
    """HISTORY_YEARS yıldan eski fiyatları ve skor fotoğraflarını siler."""
    cutoff = today - dt.timedelta(days=config.HISTORY_YEARS * 365 + config.RETENTION_BUFFER_DAYS)
    removed = conn.execute("DELETE FROM prices WHERE date < ?", (cutoff.isoformat(),)).rowcount
    conn.execute("DELETE FROM scores WHERE date < ?", (cutoff.isoformat(),))
    conn.commit()
    print(f"[budama] {cutoff} öncesi {removed} fiyat satırı silindi", flush=True)
    return removed


def update(conn: sqlite3.Connection, delay: float = 3.0, full: bool = False) -> None:
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=config.HISTORY_YEARS * 365 + config.RETENTION_BUFFER_DAYS)
    stored = None if full else conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    start = (
        max(dt.date.fromisoformat(stored) - dt.timedelta(days=config.OVERLAP_DAYS), cutoff)
        if stored
        else cutoff
    )
    client = Tefas(delay=delay)
    fetch_prices(conn, client, start, today)
    sync_categories(conn, client, today, force=full)
    sync_fvt(conn, today, force=full)
    prune(conn, today)
