from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class Fund(Base):
    __tablename__ = "funds"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True)
    title = Column(String)
    category = Column(String, nullable=True)
    prices = relationship("FundDailyPrice", back_populates="fund")
    scores = relationship("FundScore", back_populates="fund")

class FundDailyPrice(Base):
    __tablename__ = "fund_daily_prices"
    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("funds.id"))
    date = Column(Date, index=True)
    price = Column(Float)
    fund = relationship("Fund", back_populates="prices")

class FundScore(Base):
    __tablename__ = "fund_scores"
    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("funds.id"))
    date = Column(Date, index=True)
    total_score = Column(Float)
    momentum_score = Column(Float)
    risk_score = Column(Float)
    signal = Column(String)
    grade = Column(String, nullable=True)  # Harf notu sütunu
    fund = relationship("Fund", back_populates="scores")