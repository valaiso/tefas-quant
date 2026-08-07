import datetime
import sqlite3
import time
import requests

DB = "tefas.db"

DETAIL_API = "https://api.fundfy.net/api/v1/fund/detail/{code}"

API_URL = (
    "https://api.fundfy.net/api/v1/fund/detail/graph/chart/"
    "daily-cash-flow/{code}?fromDate={start}&toDate={end}"
)

INVESTOR_API_URL = (
    "https://api.fundfy.net/api/v1/fund/detail/graph/chart/"
    "daily-investors/{code}?fromDate={start}&toDate={end}"
)


def get_cash_flow_history(code):
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
            return []

        data = r.json()

        results = []

        for x in data:
            results.append(
                (code, x.get("date"), float(x.get("value", 0)))
            )

        return results

    except Exception:
        return []


def get_investor_history(code):
    try:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=30)

        url = INVESTOR_API_URL.format(
            code=code,
            start=start.strftime("%Y-%m-%d"),
            end=today.strftime("%Y-%m-%d"),
        )

        r = requests.get(url, timeout=10)

        if r.status_code != 200:
            return []

        return r.json()

    except Exception:
        return []


def get_aum(code):
    try:
        url = DETAIL_API.format(code=code)
        j = requests.get(url, timeout=10).json()

        price = float(j.get("price", 0))
        shares = float(j["fund"].get("numberOfTotalShares", 0))

        return price * shares

    except Exception:
        return 0.0


def get_aum_growth(conn, fund_id):
    try:
        current = conn.execute(
            """
            SELECT aum
            FROM fund_aum_history
            WHERE fund_id=?
            ORDER BY date DESC
            LIMIT 1
            """,
            (fund_id,)
        ).fetchone()

        old = conn.execute(
            """
            SELECT aum
            FROM fund_aum_history
            WHERE fund_id=?
            AND date <= date('now','-30 day')
            ORDER BY date DESC
            LIMIT 1
            """,
            (fund_id,)
        ).fetchone()

        if current and old and old[0] > 0:
            return ((current[0] / old[0]) - 1) * 100

        return 0.0

    except Exception:
        return 0.0


def run():
    conn = sqlite3.connect(DB)

    funds = conn.execute("SELECT id,code FROM funds").fetchall()

    history_rows = []
    metric_rows = []

    today = datetime.date.today()

    for idx, (fund_id, code) in enumerate(funds):
        daily = get_cash_flow_history(code)

        investors = get_investor_history(code)
        if code == "TLY":
            print("INVESTORS =", investors)
        investor_count = 0
        investor_growth = 0.0
        if investors:
            investor_count = int(investors[-1]["value"])

            first = float(investors[0]["value"])
            last = float(investors[-1]["value"])

            if first > 0:
                investor_growth = ((last / first) - 1) * 100

        aum = get_aum(code)
        aum_growth = get_aum_growth(conn, fund_id)

        total_30 = sum(x[2] for x in daily)

        # Son 7 günlük momentum hesaplaması
        last_7 = sum(
            x[2]
            for x in daily
            if x[1] >= (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        )

        # Pozitif gün oranı hesaplaması
        positive_ratio = (
            sum(1 for x in daily if x[2] > 0) / len(daily) if daily else 0
        )

        # Gelişmiş Karma Nakit Akış Skoru / Metriği
        cash_flow_value = (
            total_30 * 0.50
            + last_7 * 0.30
            + (positive_ratio * 1_000_000_000) * 0.20
        )

        for _, date, value in daily:
            history_rows.append((fund_id, date, value, "FUNDFY_CASH_FLOW"))

        if code == "TLY":
            print("DEBUG:", code, investor_count, investor_growth)

        conn.execute(
            """
            INSERT OR REPLACE INTO fund_aum_history
            (
            fund_id,
            date,
            aum
            )
            VALUES (?,?,?)
            """,
            (
                fund_id,
                today.strftime("%Y-%m-%d"),
                aum,
            ),
        )

        metric_rows.append(
            (
                fund_id,
                today.strftime("%Y-%m-%d"),
                investor_count,
                investor_growth,
                aum,
                aum_growth,
                cash_flow_value,  # Güncellenmiş karma metrik değeri
                "FUNDFY_CASH_FLOW",
            )
        )

        if idx % 50 == 0:
            print("İşlenen:", idx, "/", len(funds))

        time.sleep(0.05)

    conn.executemany(
        """
        INSERT OR REPLACE INTO fund_cash_flow_history
        (
        fund_id,
        date,
        cash_flow,
        source
        )
        VALUES (?,?,?,?)
        """,
        history_rows,
    )

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
        metric_rows,
    )

    conn.commit()

    print("FUNDFY CASH FLOW HISTORY YAZILDI:", len(history_rows))

    conn.close()


if __name__ == "__main__":
    run()