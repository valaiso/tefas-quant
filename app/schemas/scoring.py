from pydantic import BaseModel, Field

class FundRawInput(BaseModel):
    fund_code: str
    category: str
    return_1m: float
    return_3m: float
    return_6m: float
    return_1y: float
    return_3y: float
    alpha: float = 0.0
    information_ratio: float = 0.0
    sharpe_ratio: float
    sortino_ratio: float
    volatility: float
    max_drawdown: float
    investor_growth_1m: float
    aum_growth_1m: float
    fund_age_years: float
    management_fee: float

class FundScoreOutput(BaseModel):
    fund_code: str
    category: str
    total_score: float
    grade: str
    signal: str
    applied_penalties: list[str] = Field(default_factory=list)