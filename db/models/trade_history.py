from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from db.models.base import Base
from datetime import datetime

class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wallet_address = Column(String(42), nullable=False, index=True)
    token_id = Column(Integer, ForeignKey("tokens.id"), nullable=False)
    tx_hash = Column(String(66), unique=True, nullable=False)
    tx_type = Column(String(10), nullable=False)   # "buy", "sell", "transfer"
    
    amount = Column(Float, nullable=False)         # in tokens
    usd_value_at_tx = Column(Float, nullable=True)
    
    # For sells - large sell detection & P/L
    profit_usd = Column(Float, nullable=True)
    is_profitable = Column(Boolean, nullable=True)
    
    # Cumulative tracking for large sell %
    cumulative_bought_tokens = Column(Float, default=0.0)  # running total bought
    cumulative_sold_tokens = Column(Float, default=0.0)    # running total sold
    
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)