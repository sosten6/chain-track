import asyncio
import random
from collections import defaultdict
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

class RealTimeListener:
    def __init__(self):
        self.tracked_tokens = {}
        self.smart_wallets = {}
        self.muted_wallets = set()
        self.wallet_holdings = defaultdict(dict)
        self.last_message = None
        self.last_alert_time = {}

    def add_token(self, address: str, name: str):
        self.tracked_tokens[address.lower()] = name
        print(f"✅ Added {name} for smart wallet monitoring")

    async def start(self):
        print("🔴 Smart Wallet Monitor active - Realistic simulation")
        while True:
            await self.check_for_smart_trades()
            await asyncio.sleep(18)

    async def check_for_smart_trades(self):
        if not self.last_message:
            return

        for addr, name in self.tracked_tokens.items():
            if random.random() < 0.58:
                continue

            wallets = self.smart_wallets.get(addr, [])
            if not wallets:
                continue

            wallet = random.choice(wallets)
            if wallet['address'] in self.muted_wallets:
                continue

            key = (addr, wallet['address'])
            if key not in self.wallet_holdings or self.wallet_holdings[key] <= 0:
                self.wallet_holdings[key] = random.uniform(600000, 4500000)
                continue

            current = self.wallet_holdings[key]
            is_sell = random.random() < 0.68
            sold_percent = random.uniform(26, 47) if is_sell else 0

            # What they sold to
            sold_to_options = ["USDC", "ETH", "SOL", "WETH", "USDT"]
            sold_to = random.choice(sold_to_options)

            if is_sell:
                sold_amount = current * (sold_percent / 100)
                self.wallet_holdings[key] = max(0, current - sold_amount)

                now = asyncio.get_event_loop().time()
                if now - self.last_alert_time.get(addr, 0) < 35:
                    continue
                self.last_alert_time[addr] = now

                alert = (
                    f"🔴 <b>LARGE SELL DETECTED</b>\n\n"
                    f"Token: <b>{name}</b>\n"
                    f"Wallet: <code>{wallet['short']}</code>\n\n"
                    f"Sold: <b>{sold_percent:.1f}%</b> of holdings\n"
                    f"Sold to: <b>{sold_to}</b>\n"
                    f"Wallet ROI: +{wallet['roi']}%\n"
                    f"Win Rate: {wallet['win_rate']}%\n\n"
                    f"Smart money exit detected."
                )

                builder = InlineKeyboardBuilder()
                builder.button(text="🔇 Mute Wallet", callback_data=f"mute_wallet|{wallet['address']}")
                builder.button(text="📋 Copy Full Address", callback_data=f"copy_addr|{wallet['address']}")
                builder.button(text="📈 View All Trades", callback_data=f"wallet_trades|{wallet['address']}")
                builder.adjust(1)

                try:
                    await self.last_message.answer(alert, parse_mode="HTML", reply_markup=builder.as_markup())
                except:
                    pass

real_time_listener = RealTimeListener()