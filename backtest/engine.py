import pandas as pd
import numpy as np

class VectorizedBacktestEngine:
    def __init__(self, holding_periods=[21, 63, 126], risk_free_rate=0.40):
        self.holding_periods = holding_periods
        self.risk_free_rate = risk_free_rate

    def run(self, prices_df: pd.DataFrame, signals_df: pd.DataFrame) -> dict:
        if prices_df is None or prices_df.empty or signals_df is None or signals_df.empty:
            return {}

        if 'signal' not in signals_df.columns:
            return {}

        valid_signals = signals_df[signals_df['signal'].isin(['Güçlü AL', 'AL / İzle'])].copy()
        if valid_signals.empty:
            return {}

        prices_df = prices_df.copy()
        prices_df['date'] = pd.to_datetime(prices_df['date']).dt.normalize()
        valid_signals['date'] = pd.to_datetime(valid_signals['date']).dt.normalize()
        
        prices_df['fund_id'] = pd.to_numeric(prices_df['fund_id'], errors='coerce').astype('int64')
        valid_signals['fund_id'] = pd.to_numeric(valid_signals['fund_id'], errors='coerce').astype('int64')

        prices_df = prices_df.sort_values(by=['fund_id', 'date']).reset_index(drop=True)

        report = {}

        for period in self.holding_periods:
            trade_results = []
            
            for _, sig_row in valid_signals.iterrows():
                f_id = sig_row['fund_id']
                sig_date = sig_row['date']
                
                fund_prices = prices_df[prices_df['fund_id'] == f_id]
                if fund_prices.empty:
                    continue
                    
                entry_rows = fund_prices[fund_prices['date'] == sig_date]
                if entry_rows.empty:
                    entry_rows = fund_prices[fund_prices['date'] > sig_date]
                    if entry_rows.empty:
                        continue
                
                p_entry = float(entry_rows.iloc[0]['price'])
                actual_entry_date = entry_rows.iloc[0]['date']
                
                if pd.isna(p_entry) or p_entry <= 0:
                    continue

                future_rows = fund_prices[fund_prices['date'] > actual_entry_date]
                
                if len(future_rows) >= period:
                    p_exit = float(future_rows.iloc[period - 1]['price'])
                    exit_date = future_rows.iloc[period - 1]['date']
                    
                    ret = (p_exit - p_entry) / p_entry
                    trade_results.append({
                        'fund_id': f_id,
                        'entry_date': actual_entry_date,
                        'exit_date': exit_date,
                        'entry_price': p_entry,
                        'exit_price': p_exit,
                        'return': float(ret)
                    })

            key_name = f"{period}_days_performance"
            
            # EĞER GERÇEK İŞLEM ÇIKMAZSA ASLA SAHTE VERİ VERME, 0 DÖNDÜR
            if not trade_results:
                report[key_name] = {
                    "analyzed_signals": 0, "average_return": 0.0, "hit_ratio": 0.0,
                    "sharpe_ratio": 0.0, "max_drawdown": 0.0, "confidence_score": 0.0,
                    "trades_df": pd.DataFrame()
                }
                continue

            res_df = pd.DataFrame(trade_results)
            ret_series = res_df['return']
            
            avg_return = float(ret_series.mean() * 100)
            hit_ratio = float((ret_series > 0).mean() * 100)
            
            ret_std = float(ret_series.std())
            if pd.isna(ret_std) or ret_std == 0:
                sharpe = 0.0
            else:
                annual_factor = float(np.sqrt(252 / period))
                periodic_rf = float((self.risk_free_rate / 252) * period)
                sharpe = float(((ret_series.mean() - periodic_rf) / ret_std) * annual_factor)

            cum_returns = (1 + ret_series).cumprod()
            peak = cum_returns.cummax()
            drawdown = (cum_returns - peak) / peak
            
            if drawdown.empty:
                max_dd = 0.0
            else:
                min_dd = drawdown.min()
                max_dd = float(min_dd * 100) if not pd.isna(min_dd) else 0.0
                if max_dd > 0: 
                    max_dd = -max_dd

            confidence = min(max(hit_ratio * 0.8 + (len(res_df) * 0.2), 40.0), 99.0)

            report[key_name] = {
                "analyzed_signals": int(len(res_df)),
                "average_return": round(avg_return, 2),
                "hit_ratio": round(hit_ratio, 2),
                "sharpe_ratio": round(sharpe, 2),
                "max_drawdown": round(max_dd, 2),
                "confidence_score": round(confidence, 1),
                "trades_df": res_df
            }

        return report