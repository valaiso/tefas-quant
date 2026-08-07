import sqlite3
import requests
import datetime
import time


DB = "tefas.db"

API_URL = (
    "https://api.fundfy.net/api/v1/fund/detail/graph/chart/"
    "daily-cash-flow/{code}?fromDate={start}&toDate={end}"
)


def get_cash_flow(code):
    try:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=30)

        url = API_URL.format(
            code=code,
            start=start.strftime("%Y-%m-%d"),
            end=today.strftime("%Y-%m-%d"),
        )

        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return 0

        data = r.json()

        if not data:
            return 0

        total = sum(float(x.get("value", 0)) for x in data)

        return total

    except Exception:
        return 0


def run():
    conn = sqlite3.connect(DB)

    funds = conn.execute("SELECT id,code FROM funds").fetchall()

    today = datetime.date.today().strftime("%Y-%m-%d")

    results = []

    for idx, (fund_id, code) in enumerate(funds):
        cash_flow = get_cash_flow(code)

        results.append(
            (
                int(fund_id),
                today,
                None,
                0.0,
                None,
                0.0,
                float(cash_flow),
                "FUNDFY_CASH_FLOW",
            )
        )

        if idx % 50 == 0:
            print("İşlenen:", idx, "/", len(funds))

        time.sleep(0.05)

    conn.execute("DELETE FROM fund_flow_metrics")
    conn.executemany(
        """
    INSERT OR REPLACE INTO fund_flow_metrics
    (
    fund_id,
    date,
    investor_count,
    investor_growth_1m,
    fund_size,
    fund_size_growth_1m,
    cash_flow,
    source
    )
    VALUES (?,?,?,?,?,?,?,?)
    """,
        results,
    )

    conn.commit()

    print("FUNDFY CASH FLOW YAZILDI:", len(results))

    conn.close()


if __name__ == "__main__":
    run()