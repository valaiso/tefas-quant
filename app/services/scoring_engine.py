class QuantitativeFundScorer:
    def __init__(self, row):
        self.row = row
        self.penalties = []
        self.penalty_points = 0.0

    def calculate_scores(self):
        # 1. Performans ve Kalite Getiri (%35 Ağırlık)
        perf_sub = (self.row['rank_return_1y'] * 0.5) + (self.row['rank_alpha'] * 0.3) + (self.row['rank_info_ratio'] * 0.2)
        score_perf = perf_sub * 0.35

        # 2. Risk Analizi (%30 Ağırlık)
        risk_sub = (self.row['rank_sharpe'] * 0.3) + (self.row['rank_sortino'] * 0.3) + (self.row['rank_volatility'] * 0.2) + (self.row['rank_max_drawdown'] * 0.2)
        score_risk = risk_sub * 0.30

        # 3. Para Akışı (%15 Ağırlık)
        flow_sub = (self.row['rank_investor_growth'] * 0.5) + (self.row['rank_aum_growth'] * 0.5)
        score_flow = flow_sub * 0.15

        # 4. Kalite ve Yönetim (%10 Ağırlık)
        score_quality = self.row['rank_fund_age'] * 0.10

        # 5. Maliyet (%10 Ağırlık)
        score_cost = self.row['rank_management_fee'] * 0.10

        gross_score = score_perf + score_risk + score_flow + score_quality + score_cost

        # CEZALAR
        if self.row['investor_growth_1m'] > 15.0 and self.row['return_3m'] < 0:
            self.penalty_points += 10.0
            self.penalties.append("FOMO Alarmı (-10)")

        if self.row['rank_volatility'] < 20.0 and self.row['rank_max_drawdown'] < 20.0:
            self.penalty_points += 5.0
            self.penalties.append("Aşırı Risk Cezası (-5)")

        if self.row['management_fee'] > 3.0:
            self.penalty_points += 3.0
            self.penalties.append("Yüksek Maliyet Cezası (-3)")

        net_score = max(0.0, round(gross_score - self.penalty_points, 2))

        # Kalite Grubu
        if net_score >= 90: grade = "A+"
        elif net_score >= 80: grade = "A"
        elif net_score >= 70: grade = "B"
        elif net_score >= 60: grade = "C"
        else: grade = "Zayıf"

        # Sinyal
        if net_score >= 90: signal = "Güçlü AL"
        elif net_score >= 75: signal = "AL / İzle"
        elif net_score >= 60: signal = "Bekle"
        elif net_score >= 40: signal = "Zayıf"
        else: signal = "Uzak Dur"

        return {
            "fund_code": self.row['fund_code'],
            "category": self.row['category'],
            "total_score": net_score,
            "grade": grade,
            "signal": signal,
            "applied_penalties": self.penalties
        }