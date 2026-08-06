import requests
import sqlite3
import time
from datetime import datetime


API_KEY = "fon_X1OyzL474C5DeMWSQ7_VOO0k-twPlfDK"

DB = "tefas.db"


headers = {
    "X-API-Key": API_KEY
}


conn = sqlite3.connect(DB)
cursor = conn.cursor()


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

    url = f"https://fonoloji.com/v1/funds/{code}"


    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )


        if r.status_code == 200:

            data = r.json()

            fund = data.get("fund", {})
            portfolio = data.get("portfolio", {})
            flows = data.get("flows", {})


            d7 = flows.get("d7", {})
            d30 = flows.get("d30", {})
            d90 = flows.get("d90", {})


            cursor.execute("""
            INSERT INTO fund_external_metrics
            (
            fund_id,
            risk_score,
            aum,
            investor_count,
            flow_1w,
            flow_1m,
            flow_3m,
            beta,
            calmar_ratio,
            real_return_1y,
            portfolio_stock,
            portfolio_cash,
            portfolio_bond,
            portfolio_gold,
            category_rank,
            category_size,
            source,
            updated_at
            )

            VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)

            ON CONFLICT(fund_id)
            DO UPDATE SET

            risk_score=excluded.risk_score,
            aum=excluded.aum,
            investor_count=excluded.investor_count,
            flow_1w=excluded.flow_1w,
            flow_1m=excluded.flow_1m,
            flow_3m=excluded.flow_3m,
            beta=excluded.beta,
            calmar_ratio=excluded.calmar_ratio,
            real_return_1y=excluded.real_return_1y,
            portfolio_stock=excluded.portfolio_stock,
            portfolio_cash=excluded.portfolio_cash,
            portfolio_bond=excluded.portfolio_bond,
            portfolio_gold=excluded.portfolio_gold,
            category_rank=excluded.category_rank,
            category_size=excluded.category_size,
            updated_at=excluded.updated_at

            """,

            (

            fund_id,

            fund.get("risk_score"),

            fund.get("aum"),
            fund.get("investor_count"),

            d7.get("net_flow"),
            d30.get("net_flow"),
            d90.get("net_flow"),

            fund.get("beta_1y"),
            fund.get("calmar_1y"),
            fund.get("real_return_1y"),

            portfolio.get("stock"),
            portfolio.get("cash"),
            portfolio.get("government_bond"),

            portfolio.get("gold"),

            fund.get("category_rank"),
            fund.get("category_size"),

            "fonoloji",

            datetime.now().isoformat()

            ))


            success += 1


            print(
                f"[{index}/{len(funds)}] OK {code}"
            )


        else:

            failed += 1

            print(
                f"[{index}/{len(funds)}] ERROR {code} {r.status_code}"
            )


    except Exception as e:

        failed += 1

        print(
            f"[{index}/{len(funds)}] EXCEPTION {code}",
            e
        )


    # Fonoloji rate limit:
    time.sleep(1)


conn.commit()
conn.close()


print("\nBİTTİ")
print("Başarılı:", success)
print("Hatalı:", failed)