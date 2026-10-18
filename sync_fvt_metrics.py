"""fund_external_metrics ve fund_flow_metrics tablolarını FVT verisiyle günceller.

FVT (fvt.com.tr/api/funds/{kod}):
  AUM (toplamDeger), yatırımcı sayısı, yönetim ücreti, stopaj, fvt risk değeri,
  işlem durumu (islem: 0 = TEFAS'ta alım-satım durdurulmuş), serbest fon bayrağı
  ve ~30 günlük pay adedi / yatırımcı geçmişi (net akış ve 1A büyüme buradan).
"""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

DB = "tefas.db"
FVT_URL = "https://fvt.com.tr/api/funds/{code}"
MAX_WORKERS = 4


def _float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"accept": "application/json"}, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def history_flows(history):
    """FVT'nin ~30 günlük geçmişinden net akış ve büyüme oranları.

    Net akış(t) = (pay adedi(t) - pay adedi(t-1)) * fiyat(t)
    """
    rows = []
    for item in history or []:
        d = str(item.get("tarih", ""))[:10]
        shares, price = _float(item.get("payAdet")), _float(item.get("fiyat"))
        if d and shares is not None and price:
            rows.append(
                (d, shares, price, _float(item.get("yatirimci")), _float(item.get("toplamDeger")))
            )
    rows.sort()
    out = {"flow_1w": None, "flow_1m": None, "investor_growth_1m": None, "aum_growth_1m": None}
    if len(rows) < 2:
        return out

    last_date = datetime.strptime(rows[-1][0], "%Y-%m-%d").date()
    daily = [(rows[i][0], (rows[i][1] - rows[i - 1][1]) * rows[i][2]) for i in range(1, len(rows))]
    for key, days in [("flow_1w", 7), ("flow_1m", 30)]:
        since = (last_date - timedelta(days=days)).strftime("%Y-%m-%d")
        out[key] = sum(v for d, v in daily if d > since)

    first, last = rows[0], rows[-1]
    if first[3] and last[3] is not None:
        out["investor_growth_1m"] = (last[3] / first[3] - 1) * 100
    if first[4] and last[4] is not None:
        out["aum_growth_1m"] = (last[4] / first[4] - 1) * 100
    return out


def fetch_fund(code):
    resp = get_json(FVT_URL.format(code=code))
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    fund = data.get("fund") or {}
    if not fund:
        return None

    hist = history_flows(data.get("priceHistory"))
    # 3 aylık akış FVT'de yok (Fundfy istek sınırına takılıyor); skorlama eksik
    # dönemlerin ağırlığını diğerlerine dağıtır.
    flow = {"flow_1w": hist["flow_1w"], "flow_1m": hist["flow_1m"], "flow_3m": None}

    investor_count = _float(fund.get("yatirimci"))
    return {
        "aum": _float(fund.get("toplamDeger")),
        "investor_count": int(investor_count) if investor_count is not None else None,
        "management_fee": _float(fund.get("yonetimUcret")),
        "stopaj": _float(fund.get("stopaj")),
        "risk_score": _float(fund.get("risk")),
        "trading_active": int(fund["islem"]) if fund.get("islem") is not None else None,
        "is_serbest": int(fund["serbest"]) if fund.get("serbest") is not None else None,
        "fvt_category": fund.get("kategori"),
        **flow,
        "_investor_growth_1m": hist["investor_growth_1m"],
        "_aum_growth_1m": hist["aum_growth_1m"],
    }


def main():
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS fund_external_metrics (fund_id INTEGER PRIMARY KEY)"
    )
    existing = {r[1] for r in cursor.execute("PRAGMA table_info(fund_external_metrics)")}
    for col, col_type in [
        ("risk_score", "REAL"),
        ("aum", "REAL"),
        ("investor_count", "INTEGER"),
        ("flow_1w", "REAL"),
        ("flow_1m", "REAL"),
        ("flow_3m", "REAL"),
        ("management_fee", "REAL"),
        ("stopaj", "REAL"),
        ("trading_active", "INTEGER"),
        ("is_serbest", "INTEGER"),
        ("fvt_category", "TEXT"),
        ("source", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        if col not in existing:
            cursor.execute(f"ALTER TABLE fund_external_metrics ADD COLUMN {col} {col_type}")

    funds = cursor.execute("SELECT id, code FROM funds").fetchall()
    print("TOPLAM FON:", len(funds))

    success = failed = 0
    now = datetime.now().isoformat(timespec="seconds")
    today_str = date.today().strftime("%Y-%m-%d")
    flow_rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_fund, code): (fid, code) for fid, code in funds}
        for i, fut in enumerate(as_completed(futures), 1):
            fund_id, code = futures[fut]
            try:
                row = fut.result()
            except Exception as e:
                row = None
                print(code, "HATA", e)
            if row is None:
                failed += 1
                continue

            investor_growth = row.pop("_investor_growth_1m")
            aum_growth = row.pop("_aum_growth_1m")
            flow_rows.append(
                (
                    fund_id,
                    today_str,
                    row["investor_count"],
                    investor_growth,
                    row["aum"],
                    aum_growth,
                    row["flow_1m"],
                    "FVT_HISTORY",
                )
            )

            cols = list(row.keys())
            cursor.execute(
                f"""
                INSERT INTO fund_external_metrics (fund_id, {", ".join(cols)}, source, updated_at)
                VALUES (?, {", ".join("?" for _ in cols)}, ?, ?)
                ON CONFLICT(fund_id) DO UPDATE SET
                    {", ".join(f"{c} = excluded.{c}" for c in cols)},
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (fund_id, *row.values(), "fvt", now),
            )
            success += 1
            if i % 100 == 0:
                conn.commit()
                print(f"[{i}/{len(funds)}] tamam")

    # fund_flow_metrics: skorlamanın kullandığı yatırımcı/AUM büyümesi ve 1A akış.
    # update_fund_flow_metrics.py (Fundfy) yerine geçer; tablo tek güncel tarih tutar.
    if flow_rows:
        cursor.execute("DELETE FROM fund_flow_metrics")
        cursor.executemany(
            """
            INSERT OR REPLACE INTO fund_flow_metrics
            (fund_id, date, investor_count, investor_growth_1m, fund_size,
             fund_size_growth_1m, cash_flow, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            flow_rows,
        )

    conn.commit()
    conn.close()
    print(f"BİTTİ  Başarılı: {success}  Hatalı/veri yok: {failed}")


if __name__ == "__main__":
    main()
