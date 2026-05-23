from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    DATABASE_URL: str
    ALCHEMY_API_KEY: str
    ALCHEMY_ETH_WS_URL: str = "wss://eth-mainnet.g.alchemy.com/v2/"
    ALCHEMY_BASE_WS_URL: str = "wss://base-mainnet.g.alchemy.com/v2/"

    DEFAULT_MIN_TRADE_USD: float = 500.0
    DEFAULT_ROI_WEIGHT: float = 0.7
    DEFAULT_LARGE_SELL_THRESHOLD: float = 0.25

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()