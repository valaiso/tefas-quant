"""Son fiyatları TEFAS'tan çekip fund_daily_prices'a ekler.

- Başlangıç: DB'deki son tarihin LOOKBACK_DAYS öncesi (boşlukları ve geç
  düzeltmeleri de doldurmak için). --start ile elle verilebilir.
- Yeni TEFAS API'si tarih bazlı toplu sorguyu desteklemiyor; fon başına istek
  atılıyor (az sayıda paralel işçiyle).
- (fund_id, date) için UNIQUE index kullanılır; mevcut gün varsa fiyat
  güncellenir, 0/boş fiyatlar yazılmaz.
"""
import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import pandas as pd
from tefas import Crawler

DB = "tefas.db"
LOOKBACK_DAYS = 30
MAX_WORKERS = 4


def fetch_one(crawler, code, s_str, e_str, retries=3):
    for attempt in range(retries):
        try:
            return crawler.fetch(
                start=s_str, end=e_str, name=code, columns=["date", "code", "title", "price"]
            )
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", default=date.today().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fund_daily_prices_fund_date"
        " ON fund_daily_prices (fund_id, date)"
    )

    if args.start:
        s_str = args.start
    else:
        last = conn.execute("SELECT MAX(date) FROM fund_daily_prices").fetchone()[0]
        last_d = (
            datetime.strptime(last, "%Y-%m-%d").date()
            if last
            else date.today() - timedelta(days=4 * 365)
        )
        s_str = (last_d - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    e_str = args.end
    print(f"Fiyatlar çekiliyor: {s_str} -> {e_str}")

    crawler = Crawler()
    codes = crawler._list_fund_codes("YAT")
    if not codes:
        print("Fon listesi alınamadı.")
        return
    fund_ids = dict(conn.execute("SELECT code, id FROM funds").fetchall())

    total, empty, failed = 0, 0, 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_one, crawler, c, s_str, e_str): c for c in codes}
        for i, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            df = fut.result()
            if df is None:
                failed += 1
                continue
            df = df[pd.to_numeric(df["price"], errors="coerce") > 0]
            if df.empty:
                empty += 1
                continue

            if code not in fund_ids:
                cur = conn.execute(
                    "INSERT INTO funds (code, title, status) VALUES (?, ?, 'ACTIVE')",
                    (code, str(df["title"].iloc[-1])),
                )
                fund_ids[code] = cur.lastrowid
                print(f"Yeni fon eklendi: {code}")

            rows = [
                (fund_ids[code], pd.to_datetime(d).strftime("%Y-%m-%d"), float(p))
                for d, p in zip(df["date"], df["price"])
            ]
            conn.executemany(
                "INSERT INTO fund_daily_prices (fund_id, date, price) VALUES (?, ?, ?)"
                " ON CONFLICT(fund_id, date) DO UPDATE SET price = excluded.price",
                rows,
            )
            total += len(rows)
            if i % 100 == 0:
                conn.commit()
                print(f"[{i}/{len(codes)}] yazılan satır: {total}")

    conn.commit()
    conn.close()
    print(
        f"Bitti. Satır: {total} | veri yok: {empty} | hatalı: {failed} | fon: {len(codes)}"
    )


if __name__ == "__main__":
    main()
