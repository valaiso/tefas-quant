import sqlite3
import requests

DB = "tefas.db"

DETAIL_API = "https://api.fundfy.net/api/v1/fund/detail/{code}"


def get_shares(code):
    try:
        j = requests.get(DETAIL_API.format(code=code), timeout=10).json()

        return float(j["fund"].get("numberOfTotalShares", 0))

    except Exception:
        return 0.0


def run():

    conn = sqlite3.connect(DB)

    funds = conn.execute("SELECT id,code FROM funds").fetchall()

    rows = []

    for idx, (fund_id, code) in enumerate(funds):

        shares = get_shares(code)

        if shares <= 0:
            continue

        prices = conn.execute(
            """
            SELECT date,price
            FROM fund_daily_prices
            WHERE fund_id=?
            ORDER BY date
            """,
            (fund_id,),
        ).fetchall()

        for date, price in prices:

            if float(price) <= 0:
                continue
            aum = float(price) * shares

            rows.append((fund_id, date, aum))

        if idx % 50 == 0:
            print("İşlenen:", idx, "/", len(funds))

    conn.executemany(
        """
        INSERT OR REPLACE INTO fund_aum_history
        (
        fund_id,
        date,
        aum
        )
        VALUES (?,?,?)
        """,
        rows,
    )

    conn.commit()

    print("AUM HISTORY YAZILDI:", len(rows))

    conn.close()


if __name__ == "__main__":
    run()