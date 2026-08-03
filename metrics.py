import numpy as np
import pandas as pd

def calculate_momentum(prices, periods=[30, 90, 180, 365]):
    """Fiyat serisi üzerinden farklı periyotlarda momentum (getiri) hesaplar."""
    momentum_data = {}
    for p in periods:
        momentum_data[f'Momentum_{p}d'] = prices.pct_change(periods=p).iloc[-1]
    return pd.Series(momentum_data)

def calculate_max_drawdown(prices):
    """Zirveden en dip noktaya düşüşü (Max Drawdown) hesaplar."""
    roll_max = prices.cummax()
    drawdown = (prices - roll_max) / roll_max
    return drawdown.min()

def calculate_sharpe_ratio(returns, risk_free_rate=0.40):
    """Yıllıklandırılmış Sharpe Oranını hesaplar."""
    excess_returns = returns - (risk_free_rate / 252)
    if returns.std() == 0 or np.isnan(returns.std()):
        return 0.0
    return (excess_returns.mean() / returns.std()) * np.sqrt(252)