import asyncio
import json
import websockets
import httpx
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config.settings import settings

# Uniswap V2 Swap event topic
UNISWAP_V2_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
# Uniswap V3 Swap event topic
UNISWAP_V3_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


class RealTimeListener:
    def __init__(self):
        self.tracked_tokens = {}       # address → name
        self.tracked_chains = {}       # address → chain
        self.tracked_prices = {}       # address → price_usd
        self.smart_wallets = {}        # address → List[Dict]
        self.wallet_holdings = {}      # (token_addr, wallet_addr) → token_amount
        self.muted_wallets = set()
        self.last_message: Message | None = None
        self._evm_ws_task = None
        self._sol_ws_task = None

    def add_token(self, address: str, name: str, chain: str = "ethereum", price_usd: float = 0.0):
        self.tracked_tokens[address.lower()] = name
        self.tracked_chains[address.lower()] = chain.lower()
        self.tracked_prices[address.lower()] = price_usd
        print(f"✅ Added {name}")
        asyncio.create_task(self._load_smart_wallets(address, chain, price_usd))

    async def _load_smart_wallets(self, address: str, chain: str, price_usd: float = 0.0):
        try:
            from core.services.wallet_discovery import wallet_discovery
            holders = await wallet_discovery.get_top_holders(address, chain)
            smart = await wallet_discovery.identify_smart_wallets(holders, address, price_usd)
            self.smart_wallets[address.lower()] = smart

            # Seed known holdings from balance data
            for w in smart:
                bal = w.get("token_balance", 0)
                if bal > 0:
                    self.wallet_holdings[(address.lower(), w["address"].lower())] = bal

            print(f"   ✅ Loaded {len(smart)} smart wallets for {chain.upper()}")
        except Exception as e:
            print(f"   ❌ Load failed: {e}")

    # ─── ALERT SENDER ────────────────────────────────────────────────────────

    async def _send_alert(
        self,
        token_name: str,
        token_address: str,
        wallet: dict,
        sold_pct: float,
        sold_usd: float,
        received_symbol: str,
    ):
        if wallet["address"] in self.muted_wallets:
            return
        if not self.last_message:
            return

        pl_text = ""
        if wallet.get("bought_usd") and sold_usd > 0:
            pl = sold_usd - wallet["bought_usd"]
            pl_pct = (pl / wallet["bought_usd"]) * 100
            pl_text = f"\nRealized P/L: <b>{'+'if pl>=0 else ''}{pl_pct:.1f}% (${pl:,.0f})</b>"

        alert = (
            f"🔴 <b>LARGE SELL DETECTED</b>\n\n"
            f"Token: <b>{token_name}</b>\n"
            f"Wallet: <code>{wallet['address']}</code>\n\n"
            f"Sold: <b>{sold_pct:.1f}%</b> of holdings\n"
            f"Received: <b>{received_symbol}</b>\n"
            f"Wallet ROI: +{wallet.get('roi', '?')}%\n"
            f"Win Rate: {wallet.get('win_rate', '?')}%"
            f"{pl_text}\n\n"
            f"<i>On-chain alert 🔗</i>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🔇 Mute Wallet", callback_data=f"mute_wallet|{wallet['address']}")
        builder.adjust(1)

        try:
            await self.last_message.answer(alert, parse_mode="HTML", reply_markup=builder.as_markup())
        except Exception as e:
            print(f"   ⚠️ Alert send failed: {e}")

    # ─── EVM WEBSOCKET (Alchemy) ──────────────────────────────────────────────

    async def _evm_websocket_loop(self):
        """Connect to Alchemy WebSocket and listen for Swap events on all EVM tracked tokens."""
        chain_ws = {
            "ethereum": settings.ALCHEMY_ETH_WS_URL,
            "base": settings.ALCHEMY_BASE_WS_URL,
        }

        while True:
            try:
                # Group tokens by chain
                by_chain: dict[str, list] = {}
                for addr, chain in self.tracked_chains.items():
                    if chain in chain_ws and chain_ws[chain]:
                        by_chain.setdefault(chain, []).append(addr)

                if not by_chain:
                    await asyncio.sleep(15)
                    continue

                # Connect to each chain WS
                tasks = [
                    self._listen_evm_chain(chain, ws_url, by_chain.get(chain, []))
                    for chain, ws_url in chain_ws.items()
                    if chain in by_chain and ws_url
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                print(f"   ⚠️ EVM WS outer loop error: {e}")

            await asyncio.sleep(5)  # reconnect delay

    async def _listen_evm_chain(self, chain: str, ws_url: str, token_addresses: list):
        """
        Subscribe to ERC20 Transfer events specifically for our tracked token addresses.
        Far more efficient than subscribing to all Uniswap swaps globally.
        """
        print(f"🔌 Connecting EVM WebSocket — {chain.upper()}...")
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                ERC20_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

                # Subscribe to Transfer events for each tracked token address
                for i, token_addr in enumerate(token_addresses):
                    sub = json.dumps({
                        "jsonrpc": "2.0", "id": i + 1, "method": "eth_subscribe",
                        "params": ["logs", {
                            "address": token_addr,   # only this token
                            "topics": [ERC20_TRANSFER]
                        }]
                    })
                    await ws.send(sub)

                print(f"✅ EVM WebSocket live — {chain.upper()} ({len(token_addresses)} tokens)")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        params = msg.get("params", {})
                        result = params.get("result", {})
                        if result:
                            await self._handle_evm_transfer(result, chain, token_addresses)
                    except Exception:
                        pass

        except Exception as e:
            print(f"   ⚠️ EVM WS {chain} disconnected: {type(e).__name__}: {e}")

    async def _handle_evm_transfer(self, log: dict, chain: str, token_addresses: list):
        """
        Handle an ERC20 Transfer event directly — no receipt fetch needed.
        The log already contains token address, from, to, and amount.
        """
        if not log or not log.get("topics") or len(log["topics"]) < 3:
            return

        token_addr = log.get("address", "").lower()
        if token_addr not in token_addresses:
            return

        topics = log["topics"]
        from_addr = ("0x" + topics[1][-40:]).lower()
        ZERO = "0x0000000000000000000000000000000000000000"
        if from_addr == ZERO:
            return  # skip mints

        # Check if sender is a monitored wallet
        wallets = self.smart_wallets.get(token_addr, [])
        wallet = next((w for w in wallets if w["address"].lower() == from_addr), None)
        if not wallet:
            return

        # Decode amount
        data = log.get("data", "0x")
        try:
            amount = int(data, 16) / (10 ** 18) if data and data != "0x" else 0
        except Exception:
            return

        if amount <= 0:
            return

        holding_key = (token_addr, from_addr)
        prev_holding = self.wallet_holdings.get(holding_key, amount)
        sold_pct = (amount / prev_holding * 100) if prev_holding > 0 else 0
        self.wallet_holdings[holding_key] = max(prev_holding - amount, 0)

        if sold_pct >= 25:
            price = self.tracked_prices.get(token_addr, 0)
            sold_usd = amount * price
            token_name = self.tracked_tokens.get(token_addr, "Unknown")
            await self._send_alert(token_name, token_addr, wallet, sold_pct, sold_usd, "ETH/USDC")
            print(f"🔴 Real EVM alert: {wallet['short']} sold {sold_pct:.1f}% of {token_name}")

    # ─── SOLANA WEBSOCKET (Helius) ────────────────────────────────────────────

    async def _solana_websocket_loop(self):
        """Connect to Helius WebSocket and listen for token transfers on Solana."""
        helius_key = getattr(settings, "HELIUS_API_KEY", None)
        if not helius_key:
            print("   ⚠️ No Helius key — Solana real alerts disabled")
            return

        ws_url = f"wss://mainnet.helius-rpc.com/?api-key={helius_key}"

        while True:
            try:
                sol_tokens = [
                    addr for addr, chain in self.tracked_chains.items()
                    if chain in ("solana", "sol")
                ]
                if not sol_tokens:
                    await asyncio.sleep(15)
                    continue

                print(f"🔌 Connecting Solana WebSocket (Helius)...")
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as ws:
                    # Subscribe to logs mentioning each token
                    for token_addr in sol_tokens:
                        sub = json.dumps({
                            "jsonrpc": "2.0", "id": 1,
                            "method": "logsSubscribe",
                            "params": [
                                {"mentions": [token_addr]},
                                {"commitment": "confirmed"}
                            ]
                        })
                        await ws.send(sub)

                    print(f"✅ Solana WebSocket live — {len(sol_tokens)} tokens")

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            await self._handle_solana_log(msg)
                        except Exception:
                            pass

            except Exception as e:
                print(f"   ⚠️ Solana WS disconnected: {type(e).__name__}: {e}")

            await asyncio.sleep(5)

    async def _handle_solana_log(self, msg: dict):
        """Parse a Solana log notification and check for large sells."""
        try:
            params = msg.get("params", {})
            result = params.get("result", {})
            value = result.get("value", {})
            signature = value.get("signature", "")
            if not signature:
                return

            logs = value.get("logs", [])
            # Quick check — does this tx mention a token transfer?
            if not any("Transfer" in l or "transfer" in l for l in logs):
                return

            helius_key = settings.HELIUS_API_KEY
            async with httpx.AsyncClient(timeout=8.0) as client:
                url = f"https://api.helius.xyz/v0/transactions?api-key={helius_key}"
                resp = await client.post(url, json={"transactions": [signature]})
                if resp.status_code != 200:
                    return

                txs = resp.json()
                if not txs:
                    return

                tx = txs[0]
                for transfer in tx.get("tokenTransfers", []):
                    mint = transfer.get("mint", "").lower()
                    if mint not in self.tracked_tokens:
                        continue

                    from_addr = transfer.get("fromUserAccount", "")
                    amount = float(transfer.get("tokenAmount", 0))

                    wallets = self.smart_wallets.get(mint, [])
                    wallet = next((w for w in wallets if w["address"] == from_addr), None)
                    if not wallet:
                        continue

                    holding_key = (mint, from_addr)
                    prev_holding = self.wallet_holdings.get(holding_key, amount)
                    sold_pct = (amount / prev_holding * 100) if prev_holding > 0 else 0
                    self.wallet_holdings[holding_key] = max(prev_holding - amount, 0)

                    if sold_pct >= 25:
                        price = self.tracked_prices.get(mint, 0)
                        sold_usd = amount * price
                        token_name = self.tracked_tokens.get(mint, "Unknown")

                        # Get received symbol from native transfers
                        received = "SOL"
                        for nt in tx.get("nativeTransfers", []):
                            if nt.get("toUserAccount") == from_addr:
                                received = "SOL"
                                break

                        await self._send_alert(token_name, mint, wallet, sold_pct, sold_usd, received)
                        print(f"🔴 Real Solana alert: {wallet['short']} sold {sold_pct:.1f}% of {token_name}")

        except Exception as e:
            print(f"   ⚠️ Solana log handle error: {type(e).__name__}: {e}")

    # ─── FALLBACK POLLING (BSC + tokens without WS coverage) ─────────────────

    async def _polling_fallback_loop(self):
        """
        Poll Moralis every 60s for new transfers on BSC tokens
        and any EVM token not covered by WebSocket.
        """
        moralis_key = getattr(settings, "MORALIS_API_KEY", None)
        if not moralis_key:
            return

        last_seen: dict[str, str] = {}  # token_addr → last tx hash

        while True:
            await asyncio.sleep(60)
            try:
                bsc_tokens = [
                    addr for addr, chain in self.tracked_chains.items()
                    if chain == "bsc"
                ]

                for token_addr in bsc_tokens:
                    wallets = self.smart_wallets.get(token_addr, [])
                    if not wallets:
                        continue

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        for wallet in wallets:
                            addr = wallet.get("address", "")
                            if not addr or addr in self.muted_wallets:
                                continue

                            url = (
                                f"https://deep-index.moralis.io/api/v2.2/{addr}/erc20/transfers"
                                f"?chain=bsc&contract_addresses%5B0%5D={token_addr}&limit=5"
                            )
                            resp = await client.get(url, headers={"X-API-Key": moralis_key})
                            if resp.status_code != 200:
                                continue

                            txs = resp.json().get("result", [])
                            if not txs:
                                continue

                            latest_hash = txs[0].get("transaction_hash", "")
                            cache_key = f"{token_addr}:{addr}"
                            if last_seen.get(cache_key) == latest_hash:
                                continue
                            last_seen[cache_key] = latest_hash

                            # Check newest tx — is it a sell?
                            tx = txs[0]
                            from_addr = (tx.get("from_address") or "").lower()
                            if from_addr != addr.lower():
                                continue

                            ZERO = "0x0000000000000000000000000000000000000000"
                            if (tx.get("from_address") or "").lower() == ZERO:
                                continue

                            decimals = int(tx.get("token_decimals", 18) or 18)
                            amount = float(tx.get("value", 0) or 0) / (10 ** decimals)
                            holding_key = (token_addr, addr.lower())
                            prev = self.wallet_holdings.get(holding_key, amount)
                            sold_pct = (amount / prev * 100) if prev > 0 else 0
                            self.wallet_holdings[holding_key] = max(prev - amount, 0)

                            if sold_pct >= 25:
                                price = self.tracked_prices.get(token_addr, 0)
                                sold_usd = amount * price
                                token_name = self.tracked_tokens.get(token_addr, "Unknown")
                                await self._send_alert(token_name, token_addr, wallet, sold_pct, sold_usd, "BNB/USDT")
                                print(f"🔴 BSC poll alert: {wallet['short']} sold {sold_pct:.1f}% of {token_name}")

            except Exception as e:
                print(f"   ⚠️ Polling fallback error: {type(e).__name__}: {e}")

    # ─── MAIN START ───────────────────────────────────────────────────────────

    async def start(self):
        print("🔴 Smart Wallet Monitor active")
        # Run all listeners concurrently
        await asyncio.gather(
            self._evm_websocket_loop(),
            self._solana_websocket_loop(),
            self._polling_fallback_loop(),
            return_exceptions=True
        )


real_time_listener = RealTimeListener()