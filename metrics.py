import numpy as np
import pandas as pd

TRADING_DAYS = 252
DEFAULT_RISK_FREE_RATE = 0.20

def _get_rf():
    """Config üzerinden risk-free rate alma (config yoksa varsayılanı kullanır)."""
    try:
        from config.settings import RISK_FREE_RATE
        return float(RISK_FREE_RATE)
    except (ImportError, AttributeError):
        return DEFAULT_RISK_FREE_RATE

def calculate_total_return(prices):
    """Toplam getiriyi ondalık (decimal) olarak hesaplar (örn: 0.425 -> %42.5)."""
    if len(prices) < 2:
        return 0.0
    prices = np.asarray(prices)
    prices = prices[prices > 0]
    if len(prices) < 2:
        return 0.0
    return float(prices[-1] / prices[0] - 1.0)

def calculate_annual_return(prices):
    """Yıllıklandırılmış bileşik getiriyi (CAGR) ondalık olarak hesaplar."""
    if len(prices) < 2:
        return 0.0
    prices = np.asarray(prices)
    prices = prices[prices > 0]
    if len(prices) < 2:
        return 0.0
    days = len(prices)
    if days <= 1:
        return 0.0
    total_ret = prices[-1] / prices[0]
    if total_ret <= 0:
        return -1.0
    years = days / float(TRADING_DAYS)
    if years <= 0:
        return 0.0
    return float(total_ret ** (1.0 / years) - 1.0)

def calculate_volatility(returns):
    """Yıllıklandırılmış volatiliteyi hesaplar."""
    if len(returns) < 5:
        return 0.20
    daily_std = returns.std()
    if pd.isna(daily_std):
        return 0.20
    return float(daily_std * np.sqrt(TRADING_DAYS))

def calculate_drawdown_metrics(prices):
    """
    En büyük düşüşü (MDD - ondalık) ve gerçek Recovery Time 
    (zirveden tekrar eski zirveye ulaşma süresini - gün cinsinden) hesaplar.
    """
    if len(prices) < 2:
        return 0.0, 0
    
    prices = np.asarray(prices)
    cum_max = np.maximum.accumulate(prices)
    drawdowns = (prices - cum_max) / cum_max
    mdd = float(abs(drawdowns.min()))
    
    max_recovery_days = 0
    current_peak_idx = 0
    in_drawdown = False
    
    for i in range(len(prices)):
        if prices[i] >= cum_max[i]:
            if in_drawdown:
                recovery_duration = i - current_peak_idx
                if recovery_duration > max_recovery_days:
                    max_recovery_days = recovery_duration
                in_drawdown = False
            current_peak_idx = i
        else:
            if not in_drawdown:
                in_drawdown = True
                
    if in_drawdown:
        unrecovered_duration = len(prices) - 1 - current_peak_idx
        if unrecovered_duration > max_recovery_days:
            max_recovery_days = unrecovered_duration
            
    return mdd, int(max_recovery_days)

def calculate_downside_deviation(returns, target_annual_rate=0.0):
    """Aşağı yönlü volatiliteyi (Downside Deviation) hesaplar."""
    if len(returns) < 5:
        return 0.20
    daily_target = target_annual_rate / TRADING_DAYS
    downside_returns = returns[returns < daily_target]
    if len(downside_returns) < 2:
        return float(returns.std() * np.sqrt(TRADING_DAYS))
    return float(downside_returns.std() * np.sqrt(TRADING_DAYS))

def calculate_sharpe_ratio(returns, risk_free_rate=None):
    """Sharpe Oranı hesaplar."""
    if risk_free_rate is None:
        risk_free_rate = _get_rf()
    if len(returns) < 5:
        return 0.0
    mean_ret = returns.mean() * TRADING_DAYS
    vol = calculate_volatility(returns)
    if vol == 0:
        return 0.0
    return float((mean_ret - risk_free_rate) / vol)

def calculate_sortino_ratio(returns, risk_free_rate=None):
    """Sortino Oranı hesaplar (Yıllık risksiz oranı downside deviation'a aktarır)."""
    if risk_free_rate is None:
        risk_free_rate = _get_rf()
    if len(returns) < 5:
        return 0.0
    mean_ret = returns.mean() * TRADING_DAYS
    downside_vol = calculate_downside_deviation(returns, risk_free_rate)
    if downside_vol == 0:
        return 0.0
    return float((mean_ret - risk_free_rate) / downside_vol)

def calculate_calmar_ratio(annual_return, max_drawdown):
    """Calmar Oranı hesaplar (Yıllık Getiri / Max Drawdown)."""
    if max_drawdown <= 0:
        return 0.0
    return float(annual_return / max_drawdown)

def calculate_win_rate(returns):
    """Pozitif getirili günlerin oranını ondalık olarak hesaplar (örn: 0.58 -> %58)."""
    if len(returns) == 0:
        return 0.0
    positive_days = (returns > 0).sum()
    total_days = len(returns)
    return float(positive_days / total_days)

def calculate_var_cvar(returns, confidence_level=0.95):
    """
    np.percentile kullanarak Value at Risk (VaR) ve Conditional Value at Risk (CVaR) 
    hesaplar (Ondalık formatta pozitif kayıp oranı).
    """
    if len(returns) < 10:
        return 0.0, 0.0
    
    var_threshold = np.percentile(returns.values, (1.0 - confidence_level) * 100.0)
    var = float(abs(var_threshold))
    
    tail_losses = returns[returns <= var_threshold]
    if len(tail_losses) > 0:
        cvar = float(abs(tail_losses.mean()))
    else:
        cvar = var
        
    return var, cvar

def calculate_skewness(returns):
    """Fon getirilerinin dağılım kalitesini (Skewness / Çarpıklık) hesaplar."""
    if len(returns) < 10:
        return 0.0
    skew_val = returns.skew()
    if pd.isna(skew_val):
        return 0.0
    return float(skew_val)

def calculate_beta_and_alpha(fund_returns, benchmark_returns, risk_free_rate=None):
    """Benchmark'a göre Beta ve Alpha (Jensen's Alpha) hesaplar."""
    if risk_free_rate is None:
        risk_free_rate = _get_rf()
        
    if len(fund_returns) < 10 or len(benchmark_returns) < 10:
        return 1.0, 0.0
    
    df = pd.DataFrame({'fund': fund_returns, 'bm': benchmark_returns}).dropna()
    if len(df) < 10:
        return 1.0, 0.0
        
    cov_matrix = np.cov(df['fund'], df['bm'])
    covariance = cov_matrix[0, 1]
    benchmark_variance = cov_matrix[1, 1]
    
    if benchmark_variance == 0:
        beta = 1.0
    else:
        beta = float(covariance / benchmark_variance)
        
    fund_annual_ret = df['fund'].mean() * TRADING_DAYS
    bm_annual_ret = df['bm'].mean() * TRADING_DAYS
    
    alpha = float(fund_annual_ret - (risk_free_rate + beta * (bm_annual_ret - risk_free_rate)))
    
    return beta, alpha

def calculate_information_ratio(fund_returns, benchmark_returns):
    """Information Ratio hesaplar (Aktif Getiri / Tracking Error)."""
    if len(fund_returns) < 10 or len(benchmark_returns) < 10:
        return 0.0
        
    df = pd.DataFrame({'fund': fund_returns, 'bm': benchmark_returns}).dropna()
    if len(df) < 10:
        return 0.0
        
    active_returns = df['fund'] - df['bm']
    tracking_error = float(active_returns.std() * np.sqrt(TRADING_DAYS))
    
    if tracking_error == 0:
        return 0.0
        
    mean_active_return = float(active_returns.mean() * TRADING_DAYS)
    return mean_active_return / tracking_error