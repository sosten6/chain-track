from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from db.models.base import Base
from datetime import datetime

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(42), unique=True, nullable=False, index=True)
    chain = Column(String(10), nullable=False)
    funding_source = Column(JSONB, nullable=True)   # e.g. {"type": "binance", "tx": "..."}
    first_seen = Column(DateTime, default=datetime.utcnow)
    is_smart = Column(Boolean, default=False)