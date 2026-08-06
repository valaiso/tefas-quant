import sqlite3


conn = sqlite3.connect("tefas.db")
cursor = conn.cursor()


print("TOPLAM KAYIT:")

print(
    cursor.execute(
        "SELECT COUNT(*) FROM fund_external_metrics"
    ).fetchone()[0]
)


print("\nÖRNEK:")

row = cursor.execute("""
SELECT 
fund_id,
risk_score,
aum,
investor_count,
flow_1m,
beta,
calmar_ratio,
real_return_1y
FROM fund_external_metrics
LIMIT 5
""").fetchall()


for r in row:
    print(r)


conn.close()