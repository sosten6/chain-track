from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from db.models.base import Base
from datetime import datetime

class PerformanceScore(Base):
    __tablename__ = "performance_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), nullable=False, index=True)
    token_id = Column(Integer, ForeignKey("tokens.id"), nullable=False)
    
    roi = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    composite_score = Column(Float, default=0.0)
    
    last_calculated = Column(DateTime, default=datetime.utcnow)