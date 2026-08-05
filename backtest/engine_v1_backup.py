import pandas as pd
import numpy as np

class VectorizedBacktestEngine:
    def __init__(self, holding_periods=[21, 63, 126, 252, 756, 1260]):
        self.holding_periods = holding_periods

    def run(self, prices_df, signals_df):
        if prices_df.empty or signals_df.empty:
            return {}

        # Tarih ve sayısal format düzenlemeleri
        prices_df['date'] = pd.to_datetime(prices_df['date'])
        prices_df['price'] = pd.to_numeric(prices_df['price'], errors='coerce')
        prices_df = prices_df.dropna(subset=['price'])
        prices_df = prices_df.sort_values(['fund_id', 'date']).reset_index(drop=True)

        signals_df['date'] = pd.to_datetime(signals_df['date'])
        buy_signals = signals_df[
            signals_df['signal'].isin(
                [
                    'GÜÇLÜ AL',
                    'GÜÇLÜ AL / ELİT',
                    'AL',
                    'İZLE'
                ]
            )
        ].copy()

        # Aynı fon ve aynı gün içindeki tekrar eden sinyalleri temizle
        buy_signals = (
            buy_signals
            .sort_values(['fund_id', 'date'])
            .drop_duplicates(
                subset=['fund_id', 'date'],
                keep='last'
            )
        )

        if buy_signals.empty:
            return {}

        # Her fon için sıralı indeks (gün sırası) ver
        prices_df['row_idx'] = prices_df.groupby('fund_id').cumcount()
        
        results = {}

        for days in self.holding_periods:
            key_str = f"{days}_days_performance"
            
            # Giriş fiyatlarını ve indeksini bul
            entry_merged = pd.merge(
                buy_signals, 
                prices_df[['fund_id', 'date', 'price', 'row_idx']], 
                on=['fund_id', 'date'], 
                how='inner'
            )
            entry_merged = entry_merged.rename(columns={'price': 'entry_price', 'row_idx': 'entry_idx'})
            
            # Çıkış fiyatları için hedef indeksi belirle (giriş + N gün sonrasi)
            exit_target = prices_df[['fund_id', 'row_idx', 'date', 'price']].copy()
            exit_target['target_idx'] = exit_target['row_idx'] - days  # entry_idx ile eşleşmesi için
            
            trade_merged = pd.merge(
                entry_merged,
                exit_target[['fund_id', 'target_idx', 'date', 'price']],
                left_on=['fund_id', 'entry_idx'],
                right_on=['fund_id', 'target_idx'],
                how='inner'
            )
            trade_merged = trade_merged.rename(
                columns={
                    'price': 'price_exit',
                    'date_x': 'date_entry',
                    'date_y': 'date_exit'
                }
            )
            
            # Gerçek çıkış indeksini doğru bir şekilde tanımla
            trade_merged['exit_idx'] = (
                trade_merged['entry_idx'] + days
            )
            
            if trade_merged.empty:
                results[key_str] = {
                    "analyzed_signals": 0,
                    "average_return": 0.0,
                    "hit_ratio": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "trades_df": pd.DataFrame()
                }
                continue

            # Üst üste binen (overlapping) işlemleri engelleme (Non-overlapping trade filter)
            trade_merged = trade_merged.sort_values(['fund_id', 'entry_idx'])
            filtered_trades = []
            for _, group in trade_merged.groupby('fund_id'):
                last_exit_idx = -1
                for _, row in group.iterrows():
                    if row['entry_idx'] >= last_exit_idx:
                        filtered_trades.append(row)
                        last_exit_idx = row['exit_idx']
            
            if not filtered_trades:
                results[key_str] = {
                    "analyzed_signals": 0,
                    "average_return": 0.0,
                    "hit_ratio": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "trades_df": pd.DataFrame()
                }
                continue

            trade_merged = pd.DataFrame(filtered_trades)

            # Gerçek getiri hesabı: (Çıkış Fiyatı - Giriş Fiyatı) / Giriş Fiyatı
            trade_merged = trade_merged[
                trade_merged['entry_price'] > 0
            ].copy()
            trade_merged['return'] = (
                trade_merged['price_exit'] - trade_merged['entry_price']
            ) / trade_merged['entry_price']
            trade_merged['return'] = (
                trade_merged['return']
                .replace([np.inf, -np.inf], np.nan)
                .clip(-0.95, 10)
            )
            trades_clean = trade_merged[['fund_id', 'date_entry', 'date_exit', 'entry_price', 'price_exit', 'return']].dropna()
            
            if trades_clean.empty:
                results[key_str] = {
                    "analyzed_signals": 0,
                    "average_return": 0.0,
                    "hit_ratio": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "trades_df": pd.DataFrame()
                }
                continue

            analyzed = len(trades_clean)
            avg_ret = float(
                trades_clean['return']
                .replace([np.inf, -np.inf], np.nan)
                .mean() * 100
            )
            wins = len(trades_clean[trades_clean['return'] > 0])
            hit_ratio = float((wins / analyzed) * 100) if analyzed > 0 else 0.0
            
            # Sharpe ve Max Drawdown gerçek matematiksel hesaplamaları
            std_ret = trades_clean['return'].std()
            sharpe = float((trades_clean['return'].mean() / std_ret) * np.sqrt(252 / days)) if std_ret > 0 and not np.isnan(std_ret) else 0.0
            
            # Zaman bazlı getiri eğrisi hesaplama
            daily_returns = []
            for _, trade in trades_clean.iterrows():
                daily_return = (
                    (1 + trade['return']) ** (1 / days)
                ) - 1
                daily_returns.append(daily_return)

            equity = (
                1 + pd.Series(daily_returns)
            ).cumprod()
            peak = equity.cummax()
            drawdown = (
                equity / peak
            ) - 1
            mdd = float(
                drawdown.min() * 100
            ) if not drawdown.empty else 0.0
            

            
            results[key_str] = {
                "analyzed_signals": analyzed,
                "average_return": avg_ret,
                "hit_ratio": hit_ratio,
                "sharpe_ratio": sharpe,
                "max_drawdown": mdd,
                "trades_df": trades_clean
            }

        return results