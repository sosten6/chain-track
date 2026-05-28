import httpx
from pydantic import BaseModel
from typing import List, Optional

class TokenInfo(BaseModel):
    chain: str
    address: str   # contract address (EVM) or mint address (Solana)
    name: str
    symbol: str
    liquidity_usd: float
    price_usd: Optional[float] = None
    market_cap_usd: Optional[float] = None
    is_verified: bool = False


class TokenResolver:
    async def search_token(self, query: str) -> List[TokenInfo]:
        url = f"https://api.dexscreener.com/latest/dex/search?q={query}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                data = resp.json()

            results = []
            seen = set()

            for pair in data.get("pairs", [])[:12]:
                base = pair.get("baseToken", {})
                address = base.get("address", "")

                # Skip if no address or duplicate
                if not address or address in seen:
                    continue
                seen.add(address)

                chain = pair.get("chainId", "").upper()
                liquidity = pair.get("liquidity", {}).get("usd", 0.0)

                # Price fallback
                price = (
                    pair.get("priceUsd")
                    or base.get("priceUsd")
                    or pair.get("quoteToken", {}).get("priceUsd")
                )

                # Market cap / FDV fallback
                fdv = pair.get("fdv") or pair.get("marketCap")

                # Filter out garbage tokens
                # For EVM: contract addresses are ~42 chars
                # For Solana: mint addresses are ~44 chars (base58)
                if liquidity < 5000 or len(address) < 30:
                    continue

                results.append(TokenInfo(
                    chain=chain,
                    address=address,   # always full contract/mint address
                    name=base.get("name", "Unknown"),
                    symbol=base.get("symbol", ""),
                    liquidity_usd=float(liquidity),
                    price_usd=float(price) if price else None,
                    market_cap_usd=float(fdv) if fdv else None,
                    is_verified=pair.get("verified", False)
                ))

            return results

        except Exception as e:
            print(f"TokenResolver Error: {e}")
            return []
