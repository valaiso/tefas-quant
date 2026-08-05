import pandas as pd
import numpy as np
import json


def _percentile(series, ascending=True):
    """
    Kategori içi percentile hesaplama
    """
    if len(series) == 0:
        return series

    if ascending:
        return series.rank(pct=True) * 100
    else:
        return (1 - series.rank(pct=True)) * 100


def calculate_performance_composite(df):
    """
    Performans skoru (%40)
    """

    score = (
        _percentile(df["r_365"], True) * 0.40 +
        _percentile(df["r_180"], True) * 0.25 +
        _percentile(df["r_90"], True) * 0.20 +
        _percentile(df["r_30"], True) * 0.15
    )

    return score


def calculate_risk_composite(df):
    """
    Risk skoru (%30)
    Yüksek Sharpe/Sortino iyi,
    yüksek volatilite ve mdd kötü
    """

    score = (
        _percentile(df["sharpe"], True) * 0.35 +
        _percentile(df["sortino"], True) * 0.30 +
        _percentile(df["volatility"], False) * 0.15 +
        _percentile(df["mdd"], False) * 0.20
    )

    return score


def calculate_quality_composite(df):
    """
    Fon yaşı ve veri derinliği kalite skoru
    """

    score = (
        _percentile(df["age_years"], True) * 0.50 +
        _percentile(df["depth_score"], True) * 0.50
    )

    return score


def calculate_cashflow_composite(df):
    """
    Şimdilik yatırımcı akışı verisi olmadığı için nötr kalite
    """

    return pd.Series(
        50.0,
        index=df.index
    )


def calculate_cost_composite(df):
    """
    Şimdilik maliyet verisi yoksa nötr
    """

    return pd.Series(
        50.0,
        index=df.index
    )


def calculate_confidence(prices, first_date, last_date):
    """
    Veri derinliği ve güncelliğe göre güven skoru.
    """

    try:
        day_count = len(prices)

        age_score = min(day_count / 1250 * 100, 100)

        if day_count > 1000:
            density_score = 100
        else:
            density_score = day_count / 10

        last = pd.to_datetime(last_date)
        today = pd.Timestamp.today()

        days_old = (today - last).days

        if days_old <= 2:
            recency = 100
        else:
            recency = max(100 - days_old * 5, 10)


        confidence = (
            age_score * 0.35 +
            density_score * 0.45 +
            recency * 0.20
        )

        return round(float(confidence), 2)

    except Exception:
        return 50.0


def calculate_absolute_score(
    perf_percentile,
    risk_percentile,
    qual_percentile,
    cash_percentile,
    cost_percentile
):
    """
    Ana kalite skoru.
    Ağırlıklar:
    Performans %40
    Risk %30
    Kalite %15
    Akış %5
    Maliyet %10
    """

    score = (
        perf_percentile * 0.40 +
        risk_percentile * 0.30 +
        qual_percentile * 0.15 +
        cash_percentile * 0.05 +
        cost_percentile * 0.10
    )

    return score.round(2)


def calculate_continuous_penalty(mdd, volatility):
    """
    Sürekli risk ceza motoru.

    mdd:
    Maximum Drawdown (%)

    volatility:
    Yıllık volatilite
    """

    total_penalty = 0.0
    mdd_penalty = 0.0
    vol_penalty = 0.0


    # Derin düşüş cezası
    if mdd >= 20:
        mdd_penalty = min((mdd - 20) * 0.5, 10)
        total_penalty += mdd_penalty


    # Aşırı volatilite cezası
    if volatility >= 0.30:
        vol_penalty = min((volatility - 0.30) * 20, 10)
        total_penalty += vol_penalty


    return (
        round(total_penalty, 2),
        round(mdd_penalty, 2),
        round(vol_penalty, 2)
    )


def calculate_final_score(absolute_score, penalty, confidence):
    """
    Final skor hesaplama.

    Absolute Score:
    Ana kalite

    Penalty:
    Risk cezaları

    Confidence:
    Veri güvenilirliği
    """

    raw_score = absolute_score - penalty

    # Confidence artık çarpan değil,
    # küçük kalite düzeltmesi olarak kullanılır.
    confidence_factor = confidence / 100.0
    confidence_adjustment = (
        (confidence_factor - 0.5) * 10
    )

    final_score = raw_score + confidence_adjustment


    final_score = max(
        0,
        min(100, final_score)
    )


    return (
        round(float(final_score), 2),
        round(float(raw_score), 2),
        round(float(confidence_factor), 3)
    )


def explain_score(
    perf,
    risk,
    quality,
    cash,
    cost,
    absolute_score,
    mdd_penalty,
    vol_penalty,
    raw_score,
    confidence,
    confidence_factor,
    final_score
):
    """
    Kullanıcıya gösterilecek skor açıklaması.
    """

    data = {
        "performance_score": round(float(perf), 2),
        "risk_score": round(float(risk), 2),
        "quality_score": round(float(quality), 2),
        "cashflow_score": round(float(cash), 2),
        "cost_score": round(float(cost), 2),

        "absolute_score": round(float(absolute_score), 2),

        "penalties": {
            "max_drawdown": round(float(mdd_penalty), 2),
            "volatility": round(float(vol_penalty), 2)
        },

        "raw_score": round(float(raw_score), 2),
        "confidence": round(float(confidence), 2),
        "confidence_factor": round(float(confidence_factor), 3),

        "final_score": round(float(final_score), 2)
    }

    return json.dumps(data, ensure_ascii=False)


def calculate_category_percentile(df):
    """
    Fonları kendi kategorisi içinde percentile sıralar.
    """

    if df.empty:
        return pd.Series(dtype=float)

    result = (
        df.groupby("category")["final_score"]
        .rank(
            pct=True,
            ascending=True
        ) * 100
    )

    return result.round(2)


def calculate_rating(final_score, confidence):
    """
    Final skor + güven seviyesine göre
    harf notu ve yatırım sinyali üretir.
    """

    # Güven çok düşükse sınırlama
    if confidence < 40:
        return "C", "İZLE"

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