import pandas as pd
import numpy as np
import json


def _percentile(series, ascending=True):
    """Kategori içi percentile hesaplama"""
    if len(series) == 0:
        return series

    series = pd.to_numeric(series, errors="coerce").fillna(0)

    if ascending:
        return series.rank(pct=True) * 100
    else:
        return (1 - series.rank(pct=True)) * 100


def calculate_performance_composite(df):
    """Performans skoru"""
    score = (
        _percentile(df["r_365"], True) * 0.35
        + _percentile(df["r_180"], True) * 0.20
        + _percentile(df["r_90"], True) * 0.15
        + _percentile(df["real_return_1y"], True) * 0.30
    )
    return score.round(2)


def calculate_risk_composite(df):
    """Risk skoru"""
    score = (
        _percentile(df["sharpe"], True) * 0.35
        + _percentile(df["sortino"], True) * 0.25
        + _percentile(df["calmar"], True) * 0.15
        + _percentile(df["beta"], False) * 0.10
        + _percentile(df["volatility"], False) * 0.15
    )
    return score.round(2)


def calculate_quality_composite(df):
    """Kalite skoru (Portföy skoru)"""
    score = (
        _percentile(df["portfolio_quality"], True) * 0.60
        + _percentile(df["aum"], True) * 0.20
        + _percentile(df["alpha"], True) * 0.20
    )
    return score.round(2)


def calculate_cashflow_composite(df):
    """Yatırımcı kalitesi skoru"""

    investor_base = (
        _percentile(df["investor_count"], True) * 0.60
        + _percentile(df["investor_growth_1m"], True) * 0.20
        + _percentile(df["cash_flow"], True) * 0.20
    )

    penalty = pd.Series(0, index=df.index)

    penalty[df["investor_count"] < 1000] = -10
    penalty[
        (df["investor_count"] >= 1000) & (df["investor_count"] < 5000)
    ] = -5

    bonus = pd.Series(0, index=df.index)

    bonus[df["investor_count"] >= 5000] = 5
    bonus[df["investor_count"] >= 20000] = 10

    score = investor_base + penalty + bonus

    return score.clip(0, 100).round(2)


def calculate_cost_composite(df):
    """Maliyet skoru

    Stopaj %60 Yönetim ücreti %40
    """
    cost = (
        _percentile(df["stopaj"], False) * 0.60
        + _percentile(df["management_fee"], False) * 0.40
    )

    return cost.round(2)


def calculate_confidence(prices, first_date, last_date):
    """Veri derinliği, fon yaşı ve güncelliğe göre güven skoru hesaplar."""
    try:
        day_count = len(prices) if prices is not None else 0

        age_score = min(day_count / 1250 * 100, 100)

        if day_count >= 1000:
            density_score = 100
        else:
            density_score = min(day_count / 10, 100)

        last = pd.to_datetime(last_date) if last_date else pd.Timestamp.today()
        today = pd.Timestamp.today()

        days_old = (today - last).days

        if days_old <= 2:
            recency_score = 100
        else:
            recency_score = max(100 - days_old * 5, 10)

        if day_count >= 365:
            maturity_score = 100
        elif day_count >= 180:
            maturity_score = 75
        elif day_count >= 90:
            maturity_score = 50
        elif day_count >= 30:
            maturity_score = 25
        else:
            maturity_score = 10

        confidence = (
            age_score * 0.35
            + density_score * 0.25
            + recency_score * 0.20
            + maturity_score * 0.20
        )

        return round(float(confidence), 2)

    except Exception:
        return 50.0


def calculate_absolute_score(
    performance_score, risk_score, investor_score, portfolio_score, cost_score_val
):
    """Nihai kalite skoru

    Performans %40 Risk %20 Yatırımcı %20 Maliyet %10 Portföy Kalitesi %10
    """

    score = (
        performance_score * 0.40
        + risk_score * 0.20
        + investor_score * 0.20
        + cost_score_val * 0.10
        + portfolio_score * 0.10
    )

    return score.round(2)


def calculate_investor_penalty(investor_count):
    try:
        investor_count = int(investor_count)

        if investor_count < 100:
            return 15
        elif investor_count < 500:
            return 10
        elif investor_count < 1000:
            return 5
        else:
            return 0
    except:
        return 5


def calculate_investor_stability_adjustment(investor_count):
    try:
        investor_count = int(investor_count)

        if investor_count < 100:
            return -5
        elif investor_count < 500:
            return -3
        elif investor_count < 1000:
            return -1
        elif investor_count < 2000:
            return 0
        elif investor_count < 5000:
            return 1
        elif investor_count < 10000:
            return 2
        else:
            return 3
    except:
        return 0


def calculate_continuous_penalty(mdd, volatility):
    total_penalty = 0.0
    mdd_penalty = 0.0
    vol_penalty = 0.0

    if mdd >= 20:
        mdd_penalty = min((mdd - 20) * 0.5, 10)
        total_penalty += mdd_penalty

    if volatility >= 0.30:
        vol_penalty = min((volatility - 0.30) * 20, 10)
        total_penalty += vol_penalty

    return (
        round(total_penalty, 2),
        round(mdd_penalty, 2),
        round(vol_penalty, 2),
    )


def calculate_final_score(absolute_score, penalty, confidence):
    raw_score = absolute_score - (penalty * 0.50)

    confidence_factor = confidence / 100.0
    confidence_adjustment = (confidence_factor - 0.5) * 10

    final_score = raw_score + confidence_adjustment

    final_score = max(0, min(100, final_score))

    return (
        round(float(final_score), 2),
        round(float(raw_score), 2),
        round(float(confidence_factor), 3),
    )


def explain_score(
    perf,
    risk,
    investor,
    portfolio,
    cost,
    absolute_score,
    mdd_penalty,
    vol_penalty,
    raw_score,
    confidence,
    confidence_factor,
    final_score,
):
    data = {
        "performance_score": round(float(perf), 2),
        "risk_score": round(float(risk), 2),
        "investor_score": round(float(investor), 2),
        "portfolio_score": round(float(portfolio), 2),
        "cost_score": round(float(cost), 2),
        "absolute_score": round(float(absolute_score), 2),
        "penalties": {
            "max_drawdown": round(float(mdd_penalty), 2),
            "volatility": round(float(vol_penalty), 2),
        },
        "raw_score": round(float(raw_score), 2),
        "confidence": round(float(confidence), 2),
        "confidence_factor": round(float(confidence_factor), 3),
        "final_score": round(float(final_score), 2),
    }

    return json.dumps(data, ensure_ascii=False)


def calculate_category_percentile(df):
    if df.empty:
        return pd.Series(dtype=float)

    result = (
        df.groupby("category")["final_score"].rank(pct=True, ascending=True)
        * 100
    )

    return result.round(2)


def calculate_rating(final_score, confidence):
    if final_score >= 85:
        return "A+", "GÜÇLÜ AL"
    elif final_score >= 75:
        return "A", "AL"
    elif final_score >= 65:
        return "B", "İZLE"
    elif final_score >= 55:
        return "C", "ZAYIF"
    else:
        return "D", "UZAK DUR"


def calculate_investor_quality_score(
    investor_count, investor_change=None, cash_flow=None
):
    score = 0
    try:
        investor_count = int(investor_count or 0)
        if investor_count < 1000:
            score -= 10
        elif investor_count < 5000:
            score -= 5
        elif investor_count < 20000:
            score += 10
        else:
            score += 10
    except:
        pass

    try:
        if investor_change > 0:
            score += 1
        elif investor_change < 0:
            score -= 1
    except:
        pass

    try:
        if cash_flow > 0:
            score += 1
        elif cash_flow < 0:
            score -= 1
    except:
        pass

    return score