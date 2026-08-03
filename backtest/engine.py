import pandas as pd
import numpy as np
from typing import List, Optional

class VectorizedBacktestEngine:
    def __init__(self, holding_periods: List[int] = [21, 63, 126]):
        self.holding_periods = holding_periods

    def run(self, prices_df: pd.DataFrame, signals_df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        prices = prices_df.sort_values(by=['fund_id', 'date']).copy()
        
        for period in self.holding_periods:
            prices[f'exit_price_{period}d'] = prices.groupby('fund_id')['price'].shift(-period)
            
        bt_df = pd.merge(signals_df, prices, on=['fund_id', 'date'], how='inner')
        bt_df.rename(columns={'price': 'entry_price'}, inplace=True)

        if benchmark_df is not None:
            benchmark_df = benchmark_df.sort_values(by=['date'])
            for period in self.holding_periods:
                benchmark_df[f'bench_exit_{period}d'] = benchmark_df['price'].shift(-period)
            benchmark_df.rename(columns={'price': 'bench_entry'}, inplace=True)
            bt_df = pd.merge(bt_df, benchmark_df[['date', 'bench_entry'] + [f'bench_exit_{period}d' for period in self.holding_periods]], on='date', how='left')

        for period in self.holding_periods:
            bt_df[f'return_{period}d'] = (bt_df[f'exit_price_{period}d'] - bt_df['entry_price']) / bt_df['entry_price']
            bt_df[f'is_hit_{period}d'] = np.where(
                (bt_df['signal'] == 'BUY') & (bt_df[f'return_{period}d'] > 0), 1, 0
            )

            if benchmark_df is not None:
                bt_df[f'bench_return_{period}d'] = (bt_df[f'bench_exit_{period}d'] - bt_df['bench_entry']) / bt_df['bench_entry']
                bt_df[f'beat_benchmark_{period}d'] = np.where(
                    bt_df[f'return_{period}d'] > bt_df[f'bench_return_{period}d'], 1, 0
                )

        return bt_df

    def generate_strategy_report(self, backtest_results: pd.DataFrame) -> dict:
        report = {"total_signals": len(backtest_results)}
        for period in self.holding_periods:
            valid_results = backtest_results.dropna(subset=[f'return_{period}d'])
            if len(valid_results) == 0:
                continue
            hit_ratio = valid_results[f'is_hit_{period}d'].mean()
            avg_return = valid_results[f'return_{period}d'].mean()
            period_metrics = {
                "analyzed_signals": len(valid_results),
                "hit_ratio": round(hit_ratio * 100, 2),
                "average_return": round(avg_return * 100, 2),
                "confidence_score": round(hit_ratio * 100, 2)
            }
            if f'beat_benchmark_{period}d' in valid_results.columns:
                period_metrics["beat_benchmark_ratio"] = round(valid_results[f'beat_benchmark_{period}d'].mean() * 100, 2)
            report[f"{period}_days_performance"] = period_metrics
        return report