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
    Risk skoru (%25)
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
    Fon yaşı ve veri derinliği kalite skoru (%15)
    """

    score = (
        _percentile(df["age_years"], True) * 0.50 +
        _percentile(df["depth_score"], True) * 0.50
    )

    return score


def calculate_cashflow_composite(df):
    """
    Fon akış ve yatırımcı ilgisi skoru (%15).

    Ağırlıklar:
    - Yatırımcı büyümesi %40
    - Fon büyüklüğü büyümesi %30
    - Net para akışı %20
    - Mevcut yatırımcı tabanı %10

    Veri yoksa nötr 50 döner.
    """

    score_parts = []

    if "investor_growth_1m" in df.columns:
        investor_growth = _percentile(
            df["investor_growth_1m"].fillna(0),
            True
        )
    else:
        investor_growth = pd.Series(50, index=df.index)

    score_parts.append(investor_growth * 0.40)


    if "fund_size_growth_1m" in df.columns:
        size_growth = _percentile(
            df["fund_size_growth_1m"].fillna(0),
            True
        )
    else:
        size_growth = pd.Series(50, index=df.index)

    score_parts.append(size_growth * 0.30)


    if "cash_flow" in df.columns:
        cash_flow = _percentile(
            df["cash_flow"].fillna(0),
            True
        )
    else:
        cash_flow = pd.Series(50, index=df.index)

    score_parts.append(cash_flow * 0.20)


    if "investor_count" in df.columns:
        investor_base = _percentile(
            df["investor_count"].fillna(0),
            True
        )
    else:
        investor_base = pd.Series(50, index=df.index)

    score_parts.append(investor_base * 0.10)


    return sum(score_parts).round(2)


def calculate_cost_composite(df):
    """
    Maliyet skoru (%10 ana skorda)

    Dağılım:
    Yönetim Ücreti Avantajı %60
    Stopaj Avantajı %40

    Düşük maliyet = yüksek skor
    """

    score_parts = []

    # Yönetim ücreti
    if "management_fee" in df.columns:

        management_score = _percentile(
            df["management_fee"].fillna(
                df["management_fee"].median()
            ),
            False
        )

    else:
        management_score = pd.Series(
            50,
            index=df.index
        )

    score_parts.append(
        management_score * 0.60
    )


    # Stopaj
    if "stopaj_rate" in df.columns:

        tax_score = _percentile(
            df["stopaj_rate"].fillna(
                df["stopaj_rate"].median()
            ),
            False
        )

    else:
        tax_score = pd.Series(
            50,
            index=df.index
        )

    score_parts.append(
        tax_score * 0.40
    )


    return sum(score_parts).round(2)


def calculate_confidence(prices, first_date, last_date):
    """
    Veri derinliği, fon yaşı ve güncelliğe göre
    güven skoru hesaplar.
    """

    try:
        day_count = len(prices) if prices is not None else 0

        # Fon geçmiş uzunluğu
        age_score = min(day_count / 1250 * 100, 100)

        # Veri yoğunluğu
        if day_count >= 1000:
            density_score = 100
        else:
            density_score = min(day_count / 10, 100)

        # Güncellik
        last = pd.to_datetime(last_date) if last_date else pd.Timestamp.today()
        today = pd.Timestamp.today()

        days_old = (today - last).days

        if days_old <= 2:
            recency_score = 100
        else:
            recency_score = max(
                100 - days_old * 5,
                10
            )

        # Fon olgunluk seviyesi
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
            age_score * 0.35 +
            density_score * 0.25 +
            recency_score * 0.20 +
            maturity_score * 0.20
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
    Performans %35
    Risk %20
    Kalite %20
    Akış %15
    Maliyet %10
    """

    score = (
        perf_percentile * 0.35 +
        risk_percentile * 0.20 +
        qual_percentile * 0.20 +
        cash_percentile * 0.15 +
        cost_percentile * 0.10
    )

    return score.round(2)


def calculate_investor_penalty(investor_count):
    """
    Düşük yatırımcı sayısı riski.
    Küçük yatırımcı tabanı sürdürülebilirlik riski oluşturur.
    """

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
    """
    Yatırımcı tabanı stabilite düzeltmesi.
    Büyük fonlarda küçük bonus,
    düşük yatırımcı sayısında kontrollü risk indirimi.
    """

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

    if final_score >= 80:
        return "A+", "GÜÇLÜ AL"

    elif final_score >= 70:
        return "A", "AL"

    elif final_score >= 60:
        return "B", "İZLE"

    elif final_score >= 45:
        return "C", "ZAYIF"

    else:
        return "D", "UZAK DUR"


def calculate_investor_quality_score(
    investor_count,
    investor_change=None,
    cash_flow=None
):
    score = 0

    # yatırımcı tabanı
    try:
        investor_count = int(investor_count or 0)

        if investor_count < 1000:
            score -= 3
        elif investor_count < 5000:
            score += 0
        elif investor_count < 10000:
            score += 1
        elif investor_count < 50000:
            score += 2
        else:
            score += 3

    except:
        pass


    # yatırımcı hareketi
    try:
        if investor_change > 0:
            score += 1
        elif investor_change < 0:
            score -= 1
    except:
        pass


    # nakit akışı
    try:
        if cash_flow > 0:
            score += 1
        elif cash_flow < 0:
            score -= 1
    except:
        pass


    return score