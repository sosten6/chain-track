from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, ForeignKey, Float
from datetime import datetime
from db.models.base import Base

class TrackedWallet(Base):
    __tablename__ = "tracked_wallets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    token_id = Column(BigInteger, ForeignKey("tokens.id"), nullable=False, index=True)
    wallet_address = Column(String(42), nullable=True)   # For specific wallet tracking
    muted = Column(Boolean, default=False)
    min_trade_usd = Column(Float, default=500.0)
    added_at = Column(DateTime, default=datetime.utcnow)