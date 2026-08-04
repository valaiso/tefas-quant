from sqlalchemy import Column, Integer, Float, String, Date, ForeignKey
from database.database import Base

class Fund(Base):
    __tablename__ = "funds"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    title = Column(String)

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
    total_score = Column(Float)
    confidence_score = Column(Float)
    letter_grade = Column(String)
    signal = Column(String)