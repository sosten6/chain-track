import httpx
from pydantic import BaseModel
from typing import List, Optional

class TokenInfo(BaseModel):
    chain: str
    address: str
    name: str
    symbol: str
    liquidity_usd: float
    price_usd: Optional[float] = None
    market_cap_usd: Optional[float] = None   # NEW field
    is_verified: bool = False

class TokenResolver:
    async def search_token(self, query: str) -> List[TokenInfo]:
        url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            data = resp.json()

        results = []
        for pair in data.get("pairs", [])[:10]:  # Limit results
            chain = pair.get("chainId", "").upper()
            address = pair.get("baseToken", {}).get("address", "")
            name = pair.get("baseToken", {}).get("name", "")
            symbol = pair.get("baseToken", {}).get("symbol", "")
            liquidity = pair.get("liquidity", {}).get("usd", 0.0)

            # Fix: check multiple places for price
            price = (
                pair.get("priceUsd")
                or pair.get("baseToken", {}).get("priceUsd")
                or pair.get("quoteToken", {}).get("priceUsd")
            )

            # NEW: Market Cap / FDV
            market_cap = pair.get("fdv") or pair.get("marketCap")

            verified = pair.get("verified", False) or False

            if address and name:
                results.append(TokenInfo(
                    chain=chain,
                    address=address,
                    name=name,
                    symbol=symbol,
                    liquidity_usd=liquidity,
                    price_usd=float(price) if price else None,
                    market_cap_usd=float(market_cap) if market_cap else None,
                    is_verified=verified
                ))

        return results
