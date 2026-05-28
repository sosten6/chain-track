from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str

    # Database
    DATABASE_URL: str

    # Covalent (EVM multi-chain)
    COVALENT_API_KEY: Optional[str] = None

    # Helius (Solana)
    HELIUS_API_KEY: Optional[str] = None

    # Alchemy
    ALCHEMY_API_KEY: str
    ALCHEMY_ETH_WS_URL: Optional[str] = None
    ALCHEMY_BASE_WS_URL: Optional[str] = None

    # Block explorers
    ETHERSCAN_API_KEY: Optional[str] = None
    BASESCAN_API_KEY: Optional[str] = None
    BSCSCAN_API_KEY: Optional[str] = None

    # Moralis (free, great for BSC/BASE holders)
    MORALIS_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()