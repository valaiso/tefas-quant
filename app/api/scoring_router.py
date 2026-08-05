from app.services.ranking import calculate_category_percentiles
from fastapi import APIRouter
import pandas as pd
from app.schemas.scoring import FundRawInput, FundScoreOutput
from app.services.ranking import calculate_category_percentiles
from app.services.scoring_engine import QuantitativeFundScorer

router = APIRouter(prefix="/api/v1/scoring", tags=["Scoring Engine"])

@router.post("/calculate-batch", response_model=list[FundScoreOutput])
def calculate_batch_scores(funds: list[FundRawInput]):
    raw_data = [fund.model_dump() for fund in funds]
    df = pd.DataFrame(raw_data)
    
    if df.empty:
        return []

    

    results = []
    for _, row in ranked_df.iterrows():
        scorer = QuantitativeFundScorer(row)
        score_data = scorer.calculate_scores()
        results.append(FundScoreOutput(**score_data))

    return results