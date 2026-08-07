import json
import numpy as np
import pandas as pd


def _clip(score):
    return max(0.0, min(100.0, score))


def _score_sharpe(x):
    if pd.isna(x):
        return 50
    return _clip((x / 2.0) * 100)


def _score_sortino(x):
    if pd.isna(x):
        return 50
    return _clip((x / 3.0) * 100)


def _score_calmar(x):
    if pd.isna(x):
        return 50
    return _clip((x / 4.0) * 100)


def _score_volatility(x):
    if pd.isna(x):
        return 50
    return _clip(100 - x * 150)


def _score_drawdown(x):
    if pd.isna(x):
        return 50
    return _clip(100 - x * 150)


def _score_beta(x):
    if pd.isna(x):
        return 50
    return _clip(100 - abs(x - 1) * 50)


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
    """Performans skoru

    1 ay : %10
    2 ay : %15
    3 ay : %20
    6 ay : %25
    1 yıl : %20
    3 yıl : %5
    5 yıl : %5
    """
    score = (
        _percentile(df["r_30"], True) * 0.10
        + _percentile(df["r_60"], True) * 0.15
        + _percentile(df["r_90"], True) * 0.20
        + _percentile(df["r_180"], True) * 0.25
        + _percentile(df["r_365"], True) * 0.20
        + _percentile(df["r_1095"], True) * 0.05
        + _percentile(df["r_1825"], True) * 0.05
    )
    return score.round(2)


def calculate_risk_composite(df):
    """Risk skoru (Güncellenmiş Dengeli Dağılım)"""

    score = (
        df["volatility"].apply(_score_volatility) * 0.25
        + df["mdd"].apply(_score_drawdown) * 0.25
        + df["sharpe"].apply(_score_sharpe) * 0.20
        + df["sortino"].apply(_score_sortino) * 0.15
        + df["calmar"].apply(_score_calmar) * 0.10
        + df["beta"].apply(_score_beta) * 0.05
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
    """Investor Quality Score

    Ağırlık:
    Yatırımcı tabanı %55
    Yatırımcı büyümesi %15
    Nakit akışı kalitesi %30
    """

    def investor_base_score(x):
        try:
            x = int(x)
            if x < 1000:
                return 20
            elif x < 5000:
                return 50
            elif x < 20000:
                return 75
            else:
                return 100
        except:
            return 20

    def growth_score(x):
        try:
            x = float(x)
            if x < -10:
                return 0
            elif x < 0:
                return 40
            elif x < 5:
                return 70
            else:
                return 100
        except:
            return 50

    def cashflow_score(row):
        try:
            aum = float(row.get("aum", 0))
            flow = float(row.get("cash_flow", 0))

            if aum <= 0:
                return 50

            ratio = (flow / aum) * 100

            if ratio >= 10:
                return 100
            elif ratio >= 0:
                return 70
            elif ratio >= -5:
                return 50
            elif ratio >= -10:
                return 25
            elif ratio >= -20:
                return 10
            else:
                return 0
        except:
            return 50

    base = df["investor_count"].apply(investor_base_score)
    growth = df["investor_growth_1m"].apply(growth_score)
    cash = df.apply(cashflow_score, axis=1)

    score = base * 0.55 + growth * 0.15 + cash * 0.30

    return score.round(2)


def calculate_cost_composite(df):
    """Kategori içi maliyet skoru - yönetim ücretini aşırı cezalandırmaz"""

    if df.empty:
        return pd.Series(dtype=float)

    result = pd.Series(index=df.index, dtype=float)

    for category, group in df.groupby("category"):

        fee = pd.to_numeric(
            group["management_fee"],
            errors="coerce"
        ).fillna(group["management_fee"].median())

        # düşük ücret avantajı var ama aşırı baskı yok
        fee_score = 100 - (
            (fee - fee.min()) /
            (fee.max() - fee.min() + 0.0001)
        ) * 50

        # minimum 50 puan tabanı
        fee_score = fee_score.clip(50, 100)

        result.loc[group.index] = fee_score

    return result.round(2)


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
    performance_score,
    risk_score,
    investor_score,
    portfolio_score,
    cost_score_val,
):
    """Nihai kalite skoru

    Performans %35 Risk %25 Yatırımcı %20 Maliyet %10 Portföy Kalitesi %10
    """

    score = (
        performance_score * 0.35
        + risk_score * 0.25
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
    raw_score = absolute_score - penalty

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
        df.groupby("category")["final_score"].rank(pct=True, ascending=True) * 100
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
        if investor_count < 20000:
            if investor_change > 0:
                score += 1
            elif investor_change < 0:
                score -= 1
        else:
            if investor_change > 0:
                score += 1
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