from sqlalchemy import Column, Integer, Float, String, Date, ForeignKey
from database.database import Base

class Fund(Base):
    __tablename__ = "funds"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    title = Column(String)
    category = Column(String)
    status = Column(String)
    is_qualified = Column(Integer)
    history_completed = Column(Integer)

class FundDailyPrice(Base):
    __tablename__ = "fund_daily_prices"

    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("funds.id"))
    date = Column(Date)
    price = Column(Float)

class FundScore(Base):
    __tablename__ = "fund_scores"

    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("funds.id"))
    date = Column(Date)

    performance_score = Column(Float)
    risk_score = Column(Float)
    consistency_score = Column(Float)
    stability_score = Column(Float)

    raw_score = Column(Float)
    confidence_score = Column(Float)
    final_score = Column(Float)

    category_rank = Column(Integer)
    category_total = Column(Integer)
    category_percentile = Column(Float)

    letter_grade = Column(String)
    signal = Column(String)

    breakdown_json = Column(String)

    momentum_score = Column(Float)
    quality_score = Column(Float)
    valuation_score = Column(Float)

    absolute_score = Column(Float)
    confidence_factor = Column(Float)