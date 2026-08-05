import sqlite3
import pandas as pd
import datetime


DB = "tefas.db"


def run():

    conn = sqlite3.connect(DB)

    prices = pd.read_sql("""
        SELECT 
            fund_id,
            date,
            price
        FROM fund_daily_prices
        ORDER BY fund_id,date
    """, conn)


    if prices.empty:
        print("Fiyat datası yok")
        return


    results = []


    today = datetime.date.today().strftime("%Y-%m-%d")


    for fund_id, df in prices.groupby("fund_id"):

        df = df.sort_values("date")

        if len(df) < 60:
            continue


        price_now = df["price"].iloc[-1]

        price_30 = df["price"].iloc[-30]


        if price_30 > 0 and price_now > 0:
            growth_1m = (
                (price_now / price_30)-1
            ) * 100
        else:
            growth_1m = 0


        # fiyat ilgisi proxy
        cash_flow = growth_1m


        results.append(
            (
                int(fund_id),
                today,
                None,
                float(growth_1m),
                None,
                float(growth_1m),
                float(cash_flow),
                "PRICE_PROXY"
            )
        )


    cur = conn.cursor()


    cur.executemany("""
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
    """,results)


    conn.commit()

    print(
        "FLOW METRICS YAZILDI:",
        len(results)
    )


    conn.close()



if __name__=="__main__":
    run()