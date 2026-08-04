import pandas as pd
import numpy as np


class VectorizedBacktestEngine:

    def __init__(self, holding_periods=[21,63,126,252,756,1260], risk_free_rate=0.40):
        self.holding_periods = holding_periods
        self.risk_free_rate = risk_free_rate


    def run(self, prices_df: pd.DataFrame, signals_df: pd.DataFrame = None) -> dict:

        if prices_df is None or prices_df.empty:
            return {}


        prices_df = prices_df.copy()

        # Veri tiplerini düzelt
        prices_df['date'] = pd.to_datetime(
            prices_df['date']
        ).dt.normalize()

        prices_df['fund_id'] = pd.to_numeric(
            prices_df['fund_id'],
            errors='coerce'
        )

        prices_df['price'] = pd.to_numeric(
            prices_df['price'],
            errors='coerce'
        )

        prices_df = prices_df.dropna(
            subset=['fund_id', 'price']
        )

        prices_df['fund_id'] = prices_df['fund_id'].astype(int)


        # Tarihe göre sırala
        prices_df = prices_df.sort_values(
            by=['fund_id', 'date']
        ).reset_index(drop=True)


        # Aynı fon aynı gün tekrarlarını temizle
        prices_df = prices_df.drop_duplicates(
            subset=['fund_id', 'date'],
            keep='last'
        )


        trading_dates = sorted(
            prices_df['date'].unique()
        )


        if len(trading_dates) < 150:
            return {}


        report = {}


        # Her holding period için ayrı hesap
        for period in self.holding_periods:

            trade_results = []


            # Geçmişten bugüne aylık yeniden dengeleme
            rebalance_dates = trading_dates[21:-period:10]


            for sig_date in rebalance_dates:


                # Sadece geçmiş veri kullan
                hist_slice = prices_df[
                    prices_df['date'] <= sig_date
                ]


                pivot_prices = (
                    hist_slice
                    .pivot_table(
                        index='date',
                        columns='fund_id',
                        values='price',
                        aggfunc='last'
                    )
                    .tail(21)
                )


                if len(pivot_prices) < 21:
                    continue



                start_prices = pivot_prices.iloc[0]
                end_prices = pivot_prices.iloc[-1]


                past_returns = (
                    end_prices - start_prices
                ) / start_prices


                past_returns = past_returns.dropna()


                if past_returns.empty:
                    continue



                # O tarihte en güçlü 5 fonu seç
                top_funds = (
                    past_returns
                    .nlargest(5)
                    .index
                    .tolist()
                )



                for fund_id in top_funds:


                    future_prices = prices_df[
                        (prices_df['fund_id'] == fund_id)
                        &
                        (prices_df['date'] > sig_date)
                    ].sort_values('date')


                    if len(future_prices) < period:
                        continue



                    entry_data = prices_df[
                        (prices_df['fund_id'] == fund_id)
                        &
                        (prices_df['date'] == sig_date)
                    ]


                    if entry_data.empty:
                        continue



                    entry_price = float(
                        entry_data.iloc[0]['price']
                    )


                    exit_row = future_prices.iloc[
                        period - 1
                    ]


                    exit_price = float(
                        exit_row['price']
                    )


                    if entry_price <= 0:
                        continue



                    ret = (
                        exit_price - entry_price
                    ) / entry_price



                    trade_results.append({

                        "fund_id": int(fund_id),

                        "entry_date": sig_date,

                        "exit_date": exit_row['date'],

                        "entry_price": entry_price,

                        "exit_price": exit_price,

                        "return": float(ret)

                    })




            key_name = f"{period}_days_performance"



            if not trade_results:

                report[key_name] = {

                    "analyzed_signals":0,

                    "average_return":0.0,

                    "hit_ratio":0.0,

                    "sharpe_ratio":0.0,

                    "max_drawdown":0.0,

                    "confidence_score":0.0,

                    "trades_df":pd.DataFrame()

                }

                continue




            results = pd.DataFrame(
                trade_results
            )


            returns = results['return']


            average_return = (
                returns.mean() * 100
            )


            hit_ratio = (
                (returns > 0).mean() * 100
            )



            std = returns.std()



            if pd.isna(std) or std == 0:

                sharpe = 0

            else:

                annual_factor = np.sqrt(
                    252 / period
                )

                rf_period = (
                    self.risk_free_rate / 252
                ) * period


                sharpe = (
                    (returns.mean() - rf_period)
                    /
                    std
                ) * annual_factor




            equity = (
                1 + returns
            ).cumprod()


            peak = equity.cummax()


            drawdown = (
                equity - peak
            ) / peak


            max_drawdown = (
                drawdown.min() * 100
            )



            confidence = min(
                99,
                max(
                    40,
                    hit_ratio * 0.8
                    +
                    len(results) * 0.2
                )
            )



            report[key_name] = {

                "analyzed_signals":
                    int(len(results)),

                "average_return":
                    round(float(average_return),2),

                "hit_ratio":
                    round(float(hit_ratio),2),

                "sharpe_ratio":
                    round(float(sharpe),2),

                "max_drawdown":
                    round(float(max_drawdown),2),

                "confidence_score":
                    round(float(confidence),1),

                "trades_df":
                    results

            }


        return report