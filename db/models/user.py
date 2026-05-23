from sqlalchemy import Column, BigInteger, String, Float, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from db.models.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)   # ← Changed to BigInteger
    username = Column(String(255), nullable=True)
    
    # User preferences
    default_min_trade_usd = Column(Float, default=500.0)
    roi_weight = Column(Float, default=0.7)
    max_recursive_depth = Column(BigInteger, default=2)   # Also changed
    large_sell_threshold = Column(Float, default=0.25)
    enable_large_sell_alerts = Column(Boolean, default=True)
    
    quiet_hours_start = Column(BigInteger, default=0)
    quiet_hours_end = Column(BigInteger, default=8)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)