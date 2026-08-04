import pandas as pd
import numpy as np
import datetime
import json

# --- YARDIMCI FONKSİYONLAR ---
def _get_z_score(series):
    """Verilen bir Pandas Serisi için Z-Score hesaplar."""
    std = series.std()
    if pd.isna(std) or std == 0: 
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std

# --- HAM VERİ VE CONFIDENCE HESAPLAMALARI ---
def calculate_confidence(prices_array, first_date, last_date):
    day_count = len(prices_array)
    if day_count < 2: return 10.0

    age_score = min(100.0, (day_count / 365.0) * 100.0)
    expected_days = (pd.to_datetime(last_date) - pd.to_datetime(first_date)).days + 1
    density_score = min(100.0, (day_count / max(1, expected_days)) * 100.0) if expected_days > 0 else 100.0
    integrity_score = 100.0 if day_count > 30 else (day_count / 30.0) * 100.0
    
    days_diff = (datetime.date.today() - pd.to_datetime(last_date).date()).days
    recency_score = max(0.0, 100.0 - (days_diff * 5.0))
    
    daily_returns = pd.Series(prices_array).pct_change().dropna()
    volatility = daily_returns.std() * (255 ** 0.5) if len(daily_returns) > 5 else 0.2
    stability_score = max(0.0, min(100.0, 100.0 - (volatility * 100.0)))

    confidence = (age_score * 0.35) + (density_score * 0.25) + (integrity_score * 0.20) + (recency_score * 0.10) + (stability_score * 0.10)
    return float(min(100.0, max(10.0, confidence)))

# --- COMPOSITE FACTOR ENGINE (KATEGORİ İÇİ) ---
def calculate_performance_composite(group_df):
    z_r30 = _get_z_score(group_df['r_30'])
    z_r90 = _get_z_score(group_df['r_90'])
    z_r180 = _get_z_score(group_df['r_180'])
    z_r365 = _get_z_score(group_df['r_365'])
    comp_perf_z = (z_r30*0.2 + z_r90*0.3 + z_r180*0.2 + z_r365*0.3)
    return comp_perf_z.rank(pct=True, ascending=True) * 100.0

def calculate_risk_composite(group_df):
    z_sharpe = _get_z_score(group_df['sharpe'])
    z_sortino = _get_z_score(group_df['sortino'])
    z_vol = _get_z_score(group_df['volatility'])
    z_mdd = _get_z_score(group_df['mdd'])
    comp_risk_z = (z_sharpe*0.4 + z_sortino*0.4 - z_vol*0.1 - z_mdd*0.1)
    return comp_risk_z.rank(pct=True, ascending=True) * 100.0

def calculate_quality_composite(group_df):
    z_age = _get_z_score(group_df['age_years'])
    z_depth = _get_z_score(group_df['depth_score'])
    comp_qual_z = (z_age*0.5 + z_depth*0.5)
    return comp_qual_z.rank(pct=True, ascending=True) * 100.0

def calculate_cost_composite(group_df):
    return pd.Series(50.0, index=group_df.index)

def calculate_cashflow_composite(group_df):
    return pd.Series(50.0, index=group_df.index)

# --- SCORING ENGINE ---
def calculate_absolute_score(perf_pct, risk_pct, qual_pct, cash_pct, cost_pct):
    return (perf_pct * 0.40) + (risk_pct * 0.30) + (qual_pct * 0.10) + (cash_pct * 0.10) + (cost_pct * 0.10)

def calculate_continuous_penalty(mdd, volatility):
    mdd_pen = 0.0
    if mdd <= 35.0: mdd_pen = 0.0
    elif mdd <= 40.0: mdd_pen = (mdd - 35.0) * 0.2
    elif mdd <= 45.0: mdd_pen = 1.0 + (mdd - 40.0) * 0.2
    elif mdd <= 50.0: mdd_pen = 2.0 + (mdd - 45.0) * 0.2
    elif mdd <= 60.0: mdd_pen = 3.0 + (mdd - 50.0) * 0.1
    else: mdd_pen = min(5.0, 4.0 + (mdd - 60.0) * 0.1)

    vol_pen = 0.0
    if volatility > 0.40: vol_pen = min(5.0, (volatility - 0.40) * 10.0)

    total_pen = mdd_pen + vol_pen
    return total_pen, mdd_pen, vol_pen

def calculate_final_score(absolute_score, total_penalty, confidence):
    raw_score = absolute_score - total_penalty
    confidence_factor = 0.60 + (confidence / 100.0) * 0.40
    final_score = raw_score * confidence_factor
    return max(0.0, min(100.0, final_score)), raw_score, confidence_factor

def calculate_category_percentile(df_scored):
    return df_scored.groupby('category')['final_score'].rank(pct=True, ascending=True) * 100.0

# --- RATING & EXPLAINABILITY ---
def calculate_rating(final_score, percentile, confidence):
    # Confidence şartı kaldırıldı, Final Score zaten confidence çarpanını içeriyor
    if percentile >= 99.0 and final_score >= 85.0:
        return 'A+', 'Güçlü AL'
    elif percentile >= 95.0 and final_score >= 75.0:
        return 'A', 'AL'
    elif percentile >= 85.0 and final_score >= 70.0:
        return 'B+', 'İzle'
    elif percentile >= 70.0:
        return 'B', 'Bekle'
    elif percentile >= 50.0:
        return 'C', 'Zayıf'
    else:
        return 'D', 'Uzak Dur'

def explain_score(perf_pts, risk_pts, qual_pts, cash_pts, cost_pts, abs_score, mdd_pen, vol_pen, raw_score, confidence, confidence_factor, final_sc):
    return json.dumps({
        "Performance": f"+{round(perf_pts, 1)}",
        "Risk": f"+{round(risk_pts, 1)}",
        "Quality": f"+{round(qual_pts, 1)}",
        "CashFlow": f"+{round(cash_pts, 1)}",
        "Cost": f"+{round(cost_pts, 1)}",
        "Absolute Score": round(abs_score, 1),
        "Penalties": {
            "MDD": f"-{round(mdd_pen, 1)}" if mdd_pen > 0 else "0",
            "Volatility": f"-{round(vol_pen, 1)}" if vol_pen > 0 else "0"
        },
        "Raw Score": round(raw_score, 1),
        "Confidence": round(confidence, 1),
        "Confidence Factor": round(confidence_factor, 2),
        "Final Score": round(final_sc, 1)
    }, ensure_ascii=False)