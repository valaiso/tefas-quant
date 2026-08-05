import pandas as pd
import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring import calculate_confidence_and_score


def run_historical_scoring():

    conn = sqlite3.connect("../tefas.db")

    prices = pd.read_sql(
        """
        SELECT fund_id, date, price
        FROM fund_daily_prices
        ORDER BY fund_id, date
        """,
        conn
    )

    if prices.empty:
        print("Fiyat verisi bulunamadı.")
        return

    prices["date"] = pd.to_datetime(prices["date"])

    records = []

    grouped = prices.groupby("fund_id")

    total = len(grouped)
    counter = 0

    for fund_id, df in grouped:

        df = df.sort_values("date").reset_index(drop=True)

        if len(df) < 30:
            continue

        for i in range(30, len(df)):

            history = df.iloc[:i+1].copy()

            confidence, score, signal, grade = calculate_confidence_and_score(
                history
            )

            records.append(
                (
                    int(fund_id),
                    history.iloc[-1]["date"].strftime("%Y-%m-%d"),
                    float(score),
                    float(confidence),
                    signal,
                    grade
                )
            )

        counter += 1

        if counter % 50 == 0:
            print(f"{counter}/{total} fon tamamlandı")


    cursor = conn.cursor()

    cursor.executemany(
        """
        INSERT OR REPLACE INTO fund_scores
        (
            fund_id,
            date,
            total_score,
            confidence_score,
            signal,
            letter_grade
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        records
    )

    conn.commit()
    conn.close()

    print(f"{len(records)} geçmiş skor oluşturuldu.")


if __name__ == "__main__":
    run_historical_scoring()