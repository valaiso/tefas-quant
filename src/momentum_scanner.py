class MomentumScanner:
    def __init__(self, db_session):
        self.db = db_session

    def check_trend_filter(self, ma50, ma200):
        return ma50 > ma200

    def calculate_momentum_score(self, fund_data):
        score = (
            (fund_data.get('return_6m', 0) * 0.40) +
            (fund_data.get('trend_strength', 0) * 0.25) +
            (fund_data.get('risk_balance', 0) * 0.20) +
            (fund_data.get('volume_score', 0) * 0.15)
        )
        return round(score, 2)

    def scan_momentum(self):
        raw_funds = []
        qualified_funds = []

        for fund in raw_funds:
            if self.check_trend_filter(fund.get('ma_50', 0), fund.get('ma_200', 0)):
                fund['momentum_score'] = self.calculate_momentum_score(fund)
                qualified_funds.append(fund)

        qualified_funds.sort(key=lambda x: x['momentum_score'], reverse=True)
        return qualified_funds