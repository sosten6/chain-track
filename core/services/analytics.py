import httpx
from typing import List, Dict, Optional
from config.settings import settings

# Cache: (token_address, chain) → enriched wallet list
_roi_cache: dict = {}


class AnalyticsEngine:

    @staticmethod
    def _moralis_headers() -> dict:
        key = getattr(settings, "MORALIS_API_KEY", None)
        return {"X-API-Key": key} if key else {}

    @staticmethod
    def _helius_key() -> Optional[str]:
        return getattr(settings, "HELIUS_API_KEY", None)

    # ─── EVM ROI via Moralis ─────────────────────────────────────────────────

    @staticmethod
    async def _fetch_evm_roi(
        wallet: str,
        token_address: str,
        chain: str,
        token_price_usd: float = 0.0,
        token_decimals: int = 18,
    ) -> Dict:
        headers = AnalyticsEngine._moralis_headers()
        if not headers:
            return {}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = (
                    f"https://deep-index.moralis.io/api/v2.2/{wallet}/erc20/transfers"
                    f"?chain={chain}&contract_addresses%5B0%5D={token_address}&limit=100"
                )
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return {}

                txs = resp.json().get("result", [])
                if not txs:
                    return {}

                bought_value = 0.0
                sold_value = 0.0
                buy_count = 0
                sell_count = 0

                for tx in txs:
                    dec = int(tx.get("token_decimals", token_decimals) or token_decimals)
                    amount = float(tx.get("value", 0) or 0) / (10 ** dec)

                    # Use value_usd if available, otherwise estimate from current price
                    value_usd = float(tx.get("value_usd") or 0)
                    if value_usd == 0 and token_price_usd > 0 and amount > 0:
                        value_usd = amount * token_price_usd

                    if value_usd == 0:
                        continue  # skip if no price data at all

                    used_estimated_price = (float(tx.get("value_usd") or 0) == 0)

                    to_addr = (tx.get("to_address") or "").lower()
                    from_addr = (tx.get("from_address") or "").lower()
                    wallet_lower = wallet.lower()

                    # Skip mint events (from zero address) — not real purchases
                    ZERO = "0x0000000000000000000000000000000000000000"
                    if from_addr == ZERO:
                        continue

                    if to_addr == wallet_lower:
                        bought_value += value_usd
                        buy_count += 1
                    elif from_addr == wallet_lower:
                        sold_value += value_usd
                        sell_count += 1

                if bought_value <= 0:
                    return {}

                total_in = bought_value
                total_out = sold_value

                # If wallet has only received (no sells yet), ROI is unrealized — skip
                if sell_count == 0:
                    # Still mark as real data — wallet is holding, not sold yet
                    return {
                        "roi": 0,
                        "win_rate": 0,
                        "trades": buy_count,
                        "bought_usd": round(bought_value, 2),
                        "sold_usd": 0.0,
                        "status": "holding",
                    }

                roi = round(((total_out - total_in) / total_in) * 100, 1)

                # Win rate: were sells at higher price per token than avg buy price?
                avg_price_per_token_bought = bought_value / max(
                    sum(float(tx.get("value", 0) or 0) / (10 ** int(tx.get("token_decimals", token_decimals) or token_decimals))
                        for tx in txs if (tx.get("to_address") or "").lower() == wallet.lower()
                        and (tx.get("from_address") or "").lower() != "0x0000000000000000000000000000000000000000"),
                    1
                )
                profitable_sells = 0
                for tx in txs:
                    if (tx.get("from_address") or "").lower() != wallet.lower():
                        continue
                    dec = int(tx.get("token_decimals", token_decimals) or token_decimals)
                    amount = float(tx.get("value", 0) or 0) / (10 ** dec)
                    val = float(tx.get("value_usd") or 0)
                    if val == 0 and token_price_usd > 0 and amount > 0:
                        val = amount * token_price_usd
                    price_per_token = val / amount if amount > 0 else 0
                    if price_per_token >= avg_price_per_token_bought * 0.9:
                        profitable_sells += 1

                win_rate = round((profitable_sells / max(sell_count, 1)) * 100) if sell_count > 0 else 60

                # Check if any tx used real value_usd (not estimated)
                has_real_prices = any(
                    float(tx.get("value_usd") or 0) > 0
                    for tx in txs
                    if (tx.get("to_address") or tx.get("from_address"))
                )

                return {
                    "roi": max(round(roi, 1), -99),
                    "win_rate": min(max(win_rate, 0), 99),
                    "trades": buy_count + sell_count,
                    "bought_usd": round(bought_value, 2),
                    "sold_usd": round(sold_value, 2),
                    "price_estimated": not has_real_prices,
                }

        except Exception as e:
            print(f"   ⚠️ EVM ROI fetch failed for {wallet[:10]}: {type(e).__name__}: {e}")
            return {}

    # ─── Solana ROI via Helius ────────────────────────────────────────────────

    @staticmethod
    async def _fetch_solana_roi(wallet: str, token_address: str) -> Dict:
        helius_key = AnalyticsEngine._helius_key()
        if not helius_key:
            return {}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = (
                    f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
                    f"?api-key={helius_key}&limit=100&type=SWAP"
                )
                resp = await client.get(url)
                if resp.status_code != 200:
                    return {}

                txs = resp.json()
                if not txs:
                    return {}

                bought = 0.0
                sold = 0.0
                buy_count = 0
                sell_count = 0

                for tx in txs:
                    for transfer in tx.get("tokenTransfers", []):
                        if transfer.get("mint", "").lower() != token_address.lower():
                            continue
                        amount = float(transfer.get("tokenAmount", 0))
                        if transfer.get("toUserAccount") == wallet:
                            bought += amount
                            buy_count += 1
                        elif transfer.get("fromUserAccount") == wallet:
                            sold += amount
                            sell_count += 1

                if bought <= 0:
                    return {}

                roi = round(((sold - bought) / bought) * 100, 1)
                win_rate = min(round((sell_count / max(buy_count, 1)) * 60 + 40), 99)

                return {
                    "roi": max(roi, -99),
                    "win_rate": win_rate,
                    "trades": buy_count + sell_count,
                }

        except Exception as e:
            print(f"   ⚠️ Solana ROI fetch failed for {wallet[:10]}: {type(e).__name__}: {e}")
            return {}

    # ─── Core enrichment (with caching) ──────────────────────────────────────

    @staticmethod
    async def enrich_wallets_with_roi(
        wallets: List[Dict],
        token_address: str,
        chain: str,
        token_price_usd: float = 0.0,
    ) -> List[Dict]:
        cache_key = (token_address.lower(), chain.lower())

        # Return cached result if available
        if cache_key in _roi_cache:
            print(f"   ℹ️ ROI cache hit for {token_address[:12]}")
            return _roi_cache[cache_key]

        chain_lower = chain.lower()
        moralis_chain = {"ethereum": "eth", "base": "base", "bsc": "bsc"}.get(chain_lower)

        enriched = []
        for w in wallets:
            addr = w.get("address", "")
            real_data = {}

            if moralis_chain and addr:
                real_data = await AnalyticsEngine._fetch_evm_roi(
                    addr, token_address, moralis_chain,
                    token_price_usd=token_price_usd,
                    token_decimals=18,
                )
            elif chain_lower in ("solana", "sol") and addr:
                real_data = await AnalyticsEngine._fetch_solana_roi(addr, token_address)

            if real_data:
                w = {**w, **real_data, "roi_is_real": True}
                print(f"   ✅ Real ROI for {w['short']}: {real_data['roi']}%")
            else:
                w = {**w, "roi_is_real": False}

            enriched.append(w)

        # Cache for this session
        _roi_cache[cache_key] = enriched
        return enriched

    # ─── Public API ──────────────────────────────────────────────────────────

    @staticmethod
    async def get_top_wallets_by_roi(
        token_address: str,
        chain: str = "ethereum",
        wallets: Optional[List[Dict]] = None,
        token_price_usd: float = 0.0,
    ) -> List[Dict]:
        if not wallets:
            return []
        enriched = await AnalyticsEngine.enrich_wallets_with_roi(
            wallets, token_address, chain, token_price_usd
        )
        return sorted(enriched, key=lambda x: x.get("roi", 0), reverse=True)

    @staticmethod
    async def get_top_wallets_by_score(
        token_address: str,
        chain: str = "ethereum",
        wallets: Optional[List[Dict]] = None,
        token_price_usd: float = 0.0,
    ) -> List[Dict]:
        if not wallets:
            return []
        enriched = await AnalyticsEngine.enrich_wallets_with_roi(
            wallets, token_address, chain, token_price_usd
        )
        for w in enriched:
            w["score"] = round(w.get("roi", 0) * 0.7 + w.get("win_rate", 0) * 0.3, 1)
        return sorted(enriched, key=lambda x: x["score"], reverse=True)


def invalidate_cache(token_address: str, chain: str):
    """Call when a token is re-tracked to clear stale ROI cache."""
    key = (token_address.lower(), chain.lower())
    _roi_cache.pop(key, None)


analytics_engine = AnalyticsEngine()