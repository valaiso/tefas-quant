import requests
import sqlite3
import time
from datetime import datetime

DB = "tefas.db"

conn = sqlite3.connect(DB)
cursor = conn.cursor()

# Tablo ve eksik kolonların varlığını garantiye alalım
cursor.execute("""
CREATE TABLE IF NOT EXISTS fund_external_metrics (
    fund_id INTEGER PRIMARY KEY,
    investor_count INTEGER,
    aum REAL,
    management_fee REAL,
    stopaj REAL,
    portfolio_gold REAL,
    category_rank INTEGER,
    category_size INTEGER,
    source TEXT,
    updated_at TEXT
)
""")

for col, col_type in [
    ("management_fee", "REAL"), 
    ("stopaj", "REAL"), 
    ("portfolio_gold", "REAL"), 
    ("category_rank", "INTEGER"), 
    ("category_size", "INTEGER")
]:
    try:
        cursor.execute(f"ALTER TABLE fund_external_metrics ADD COLUMN {col} {col_type}")
    except sqlite3.OperationalError:
        pass

cursor.execute("""
SELECT id, code
FROM funds
WHERE status='ACTIVE'
""")

funds = cursor.fetchall()

print("TOPLAM FON:", len(funds))

success = 0
failed = 0

for index, (fund_id, code) in enumerate(funds, start=1):
    try:
        url = f"https://fvt.com.tr/api/funds/{code}"
        headers = {
            "accept": "application/json"
        }

        r = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        if r.status_code == 200:
            resp = r.json()
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            
            history = data.get("priceHistory", [])

            investor_count = 0
            # En güncel sıfır olmayan yatırımcı sayısını al
            if isinstance(history, list):
                for item in history:
                    value = float(item.get("yatirimci", 0) or 0)
                    if value > 0:
                        investor_count = int(value)
                        break

            # Yönetim ücreti ve stopaj verilerini doğru JSON seviyesinden (data -> fund) güvenli çekme
            fund_data = data.get("fund", {})
            management_fee = float(fund_data.get("yonetimUcret", fund_data.get("management_fee", 0)) or 0)
            stopaj = float(fund_data.get("stopaj", fund_data.get("withholding_tax", 0)) or 0)

            # UPSERT ile veritabanı güncelleme/kayıt işlemi
            cursor.execute("""
            INSERT INTO fund_external_metrics (
                fund_id, 
                investor_count, 
                management_fee, 
                stopaj, 
                source, 
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(fund_id) DO UPDATE SET
                investor_count = excluded.investor_count,
                management_fee = excluded.management_fee,
                stopaj = excluded.stopaj,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                fund_id,
                investor_count,
                management_fee,
                stopaj,
                "fvt",
                datetime.now().isoformat()
            ))

            success += 1
            print(f"[{index}/{len(funds)}] {code} -> Yatırımcı: {investor_count} | Yönetim Ücreti: {management_fee} | Stopaj: {stopaj}")

        else:
            failed += 1
            print(code, "HTTP", r.status_code)

    except Exception as e:
        failed += 1
        print(code, e)

    time.sleep(0.3)

conn.commit()
conn.close()

print()
print("BİTTİ")
print("Başarılı:", success)
print("Hatalı:", failed)