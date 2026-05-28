from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, BigInteger
from db.models.base import Base
from datetime import datetime

class Token(Base):
    __tablename__ = "tokens"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    chain = Column(String(10), nullable=False)
    contract_address = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    liquidity_usd = Column(Float, default=0.0)
    price_usd = Column(Float, default=0.0, nullable=True)        # ← NEW
    market_cap_usd = Column(Float, default=0.0, nullable=True)   # ← NEW
    is_verified = Column(Boolean, default=False)
    last_metadata_update = Column(DateTime, default=datetime.utcnow)