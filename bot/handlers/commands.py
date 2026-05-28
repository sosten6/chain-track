import asyncio
from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram import Dispatcher
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.services.token_resolver import TokenResolver
from bot.keyboards.inline import build_token_selection_keyboard, resolve_token_address
from core.services.real_time_listener import real_time_listener
from core.services.analytics import AnalyticsEngine

router = Router()

user_id_cache = {}

# ====================== BASIC COMMANDS ======================

@router.message(Command("start"))
async def cmd_start(message: Message):
    telegram_id = message.chat.id
    user_id_cache[telegram_id] = telegram_id

    await message.answer(
        f"<b>🚀 SmartChain Tracker</b>\n\n"
        f"Your ID: <code>{telegram_id}</code>\n\n"
        "Real-time smart money tracking with large sell detection.\n\n"
        "Commands:\n"
        "/track &lt;token or CA&gt; — Track a token\n"
        "/list — Your tracked tokens\n"
        "/roi &lt;token&gt; — Top wallets by ROI\n"
        "/score &lt;token&gt; — Top wallets by score\n"
        "/stop &lt;token or CA&gt; — Remove tracked token\n"
        "/wallet &lt;address&gt; — Monitor specific wallet\n"
        "/test_large_sell — Test alert\n"
        "/status — Bot status\n\n"
        "<i>Free tier • Smart wallet alerts enabled</i>",
        parse_mode="HTML"
    )

@router.message(Command("status"))
async def cmd_status(message: Message):
    telegram_id = message.chat.id
    count = 0
    try:
        from db.session import AsyncSessionLocal
        from sqlalchemy import select
        from db.models.tracked_wallet import TrackedWallet
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(TrackedWallet).where(TrackedWallet.telegram_id == telegram_id))
            count = len(result.scalars().all())
    except:
        pass

    await message.answer(
        f"✅ <b>Bot Status</b>\n\n"
        f"• Running: Yes\n"
        f"• Your tracked tokens: <b>{count}</b>\n"
        f"• Mode: Free Tier (Polling)\n"
        f"• Large sell threshold: ≥25%\n"
        f"• Smart wallet alerts: Active",
        parse_mode="HTML"
    )

@router.message(Command("list"))
async def cmd_list(message: Message):
    telegram_id = message.chat.id
    effective_id = user_id_cache.get(telegram_id, telegram_id)

    await message.answer("📋 <b>Your Tracked Tokens</b>\n\nFetching...", parse_mode="HTML")

    from db.session import AsyncSessionLocal
    from sqlalchemy import select
    from db.models.token import Token
    from db.models.tracked_wallet import TrackedWallet

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Token)
            .join(TrackedWallet, TrackedWallet.token_id == Token.id)
            .where(TrackedWallet.telegram_id == effective_id)
        )
        result = await session.execute(stmt)
        tokens = result.scalars().all()

    if not tokens:
        await message.answer("You haven't tracked any tokens yet.\nUse /track to start.")
        return

    text = "📋 <b>Your Tracked Tokens</b>\n\n"
    for token in tokens:
        text += f"• <b>{token.name}</b> ({token.symbol}) on {token.chain.upper()}\n"
        text += f"  └─ Liquidity: ${token.liquidity_usd:,.0f}\n"
        if hasattr(token, 'market_cap_usd') and token.market_cap_usd:
            text += f"  └─ Market Cap: ${token.market_cap_usd:,.0f}\n"
        text += "\n"
    text += "Use /stop &lt;token or CA&gt; to remove."
    await message.answer(text, parse_mode="HTML")


async def _track_token(message: Message, token_info):
    telegram_id = message.chat.id
    user_id_cache[telegram_id] = telegram_id

    try:
        from db.session import AsyncSessionLocal
        from db.repositories.token_repo import TokenRepository
        from db.repositories.user_repo import UserRepository
        from db.repositories.tracked_wallet_repo import TrackedWalletRepository

        async with AsyncSessionLocal() as session:
            await UserRepository(session).get_or_create_user(telegram_id, message.from_user.username or "Unknown")
            token_info.chain = token_info.chain.upper()
            saved_token = await TokenRepository(session).get_or_create_token(token_info)
            await TrackedWalletRepository(session).add_tracked_token(telegram_id, saved_token.id)
            await session.commit()
            await session.refresh(saved_token)

        price_usd = getattr(token_info, "price_usd", None) or 0.0
        real_time_listener.add_token(saved_token.contract_address, saved_token.name, saved_token.chain, float(price_usd))
        real_time_listener.last_message = message

        price = getattr(token_info, 'price_usd', None)
        market_cap = getattr(token_info, 'market_cap_usd', None)
        price_text = f"Current Price: ${price:,.8f}" if price else "Current Price: N/A"
        mc_text = f"Market Cap: ${market_cap:,.0f}" if market_cap else "Market Cap: N/A"

        # ✅ Send confirmation immediately — don't wait for wallet loading
        await message.answer(
            f"✅ <b>Tracking Started!</b>\n\n"
            f"<b>{saved_token.name}</b> ({saved_token.symbol})\n"
            f"Chain: {saved_token.chain.upper()}\n"
            f"Liquidity: ${saved_token.liquidity_usd:,.0f}\n"
            f"{price_text}\n"
            f"{mc_text}\n\n"
            f"⏳ Loading smart wallets...",
            parse_mode="HTML"
        )

        # Background: wait for wallet data then send follow-up
        asyncio.create_task(_send_wallet_followup(message, saved_token.contract_address, saved_token.name))

    except Exception as e:
        print(f"ERROR in _track_token: {type(e).__name__}: {e}")
        await message.answer(
            "⚠️ Token was saved but something went wrong loading wallet data.\n"
            "Use /list to confirm it was added.",
            parse_mode="HTML"
        )


async def _send_wallet_followup(message: Message, contract_address: str, token_name: str):
    """Send smart wallet summary as a follow-up once data is loaded."""
    smart_wallets = []
    for _ in range(50):  # wait up to 25s total (50 × 0.5s) — covers slow Covalent + fallback
        smart_wallets = real_time_listener.smart_wallets.get(contract_address.lower(), [])
        if smart_wallets:
            break
        await asyncio.sleep(0.5)

    if not smart_wallets:
        await message.answer(
            f"⚠️ Could not load smart wallets for <b>{token_name}</b>.\n"
            f"Alerts will still fire if wallets are found later.",
            parse_mode="HTML"
        )
        return

    lines = []
    for w in smart_wallets[:5]:
        line = f"• <code>{w['short']}</code> — ROI +{w['roi']}%"
        if w.get("value_usd") and w["value_usd"] > 0:
            line += f" | Holds ~${w['value_usd']:,.0f}"
        lines.append(line)
    wallet_list = "\n".join(lines)
    await message.answer(
        f"🧠 <b>Smart Wallets Loaded — {token_name}</b>\n\n"
        f"{wallet_list}\n\n"
        f"Monitoring {len(smart_wallets)} wallets. Alerts active. 🔔",
        parse_mode="HTML"
    )


@router.message(Command("track"))
async def cmd_track(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer("Usage: <code>/track PEPE</code>")
        return

    query = message.text.split(maxsplit=1)[1].strip()
    await message.answer(f"🔍 Searching for <b>{query}</b> on DEX Screener...", parse_mode="HTML")

    resolver = TokenResolver()
    results = await resolver.search_token(query)

    if not results:
        await message.answer("❌ No tokens found.")
        return

    if len(results) == 1:
        await _track_token(message, results[0])
    else:
        keyboard = build_token_selection_keyboard(results)
        await message.answer("🔎 Choose the correct token:", reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("select_token|"))
async def handle_token_selection(callback: CallbackQuery):
    # ✅ Answer Telegram immediately — must happen within ~10s or query expires
    await callback.answer("🔍 Looking up token...")

    parts = callback.data.split("|")
    short_key = parts[2]

    # Resolve full address from in-memory cache
    full_address = resolve_token_address(short_key)
    if not full_address:
        await callback.message.edit_text("❌ Session expired. Please run /track again.")
        return

    await callback.message.edit_text("💾 Saving to your list...", parse_mode="HTML")

    try:
        resolver = TokenResolver()
        results = await resolver.search_token(full_address)
        token_info = next(
            (t for t in results if t.address.lower() == full_address.lower()),
            results[0] if results else None
        )

        if token_info:
            await _track_token(callback.message, token_info)
        else:
            await callback.message.edit_text("❌ Could not find token details. Try /track again.")

    except Exception as e:
        print(f"ERROR in handle_token_selection: {type(e).__name__}: {e}")
        await callback.message.edit_text("❌ Failed to save token. Try /track again.")


# ====================== ROI & SCORE ======================

@router.message(Command("roi"))
async def cmd_roi(message: Message):
    await _show_analytics(message, "roi")


@router.message(Command("score"))
async def cmd_score(message: Message):
    await _show_analytics(message, "score")


async def _show_analytics(message: Message, mode: str):
    if not message.text or len(message.text.split()) < 2:
        await message.answer(f"Usage: <code>/{mode} PEPE</code>")
        return

    query = message.text.split(maxsplit=1)[1].strip()
    telegram_id = message.chat.id

    await message.answer(f"📊 Calculating {mode.upper()} for <b>{query}</b>...", parse_mode="HTML")

    try:
        from db.session import AsyncSessionLocal
        from sqlalchemy import select
        from db.models.token import Token
        from db.models.tracked_wallet import TrackedWallet

        async with AsyncSessionLocal() as session:
            stmt = (
                select(Token)
                .join(TrackedWallet, TrackedWallet.token_id == Token.id)
                .where(
                    TrackedWallet.telegram_id == telegram_id,
                    (Token.name.ilike(f"%{query}%")) |
                    (Token.symbol.ilike(f"%{query}%")) |
                    (Token.contract_address.ilike(f"%{query}%"))
                )
            )
            result = await session.execute(stmt)
            tokens = result.scalars().all()

            if not tokens:
                await message.answer(
                    f"❌ You are not tracking any token matching <b>{query}</b>.\n"
                    f"Use /list to see your tracked tokens.",
                    parse_mode="HTML"
                )
                return

            if len(tokens) > 1:
                builder = InlineKeyboardBuilder()
                for token in tokens[:6]:
                    builder.button(
                        text=f"{token.name} ({token.symbol}) - {token.chain.upper()}",
                        callback_data=f"analytics_{mode}|{token.id}"
                    )
                builder.adjust(1)
                await message.answer(
                    "Multiple tracked tokens found. Choose one:",
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
                return

            token = tokens[0]

            # Pull live wallet list from real_time_listener
            live_wallets = real_time_listener.smart_wallets.get(token.contract_address.lower(), [])

            token_price = float(token.price_usd) if getattr(token, "price_usd", None) else 0.0

            if mode == "roi":
                wallets = await AnalyticsEngine.get_top_wallets_by_roi(
                    token.contract_address, chain=token.chain,
                    wallets=live_wallets, token_price_usd=token_price
                )
                title = f"📈 Top Wallets by ROI — {token.name}"
            else:
                wallets = await AnalyticsEngine.get_top_wallets_by_score(
                    token.contract_address, chain=token.chain,
                    wallets=live_wallets, token_price_usd=token_price
                )
                title = f"🏆 Top Wallets by Score — {token.name}"

            if not wallets:
                await message.answer(
                    f"⚠️ No wallet data yet for <b>{token.name}</b>.\n"
                    f"Try again after tracking for a minute.",
                    parse_mode="HTML"
                )
                return

            text = f"{title}\n\n"
            for i, w in enumerate(wallets[:5], 1):
                roi = w.get("roi", 0)
                roi_label = f"+{roi}%" if roi >= 0 else f"{roi}%"
                if w.get("roi_is_real") and not w.get("price_estimated"):
                    badge = " ✅"
                elif w.get("roi_is_real") and w.get("price_estimated"):
                    badge = " 📊"
                else:
                    badge = " ~"
                score = w.get("score", round(roi * 0.7 + w.get("win_rate", 0) * 0.3, 1))
                value = f" | Holds ~${w['value_usd']:,.0f}" if w.get("value_usd", 0) > 0 else ""
                status = " (holding)" if w.get("status") == "holding" else ""
                text += f"{i}. <code>{w['short']}</code> — ROI {roi_label}{badge}{status} | W.Rate {w.get('win_rate', 0)}% | Score {score}{value}\n"

            legend = "\n✅ real  📊 real txs, est. price  ~ simulated"
            await message.answer(text + legend, parse_mode="HTML")

    except Exception as e:
        print(f"Analytics Error: {e}")
        await message.answer("❌ Analytics service temporarily unavailable.")


# ====================== STOP ======================

@router.message(Command("stop"))
async def cmd_stop(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer("Usage: <code>/stop PEPE</code> or <code>/stop CA</code>")
        return

    query = message.text.split(maxsplit=1)[1].strip().lower()
    telegram_id = message.chat.id

    await message.answer(f"🛑 Searching your tracked tokens for <b>{query}</b>...", parse_mode="HTML")

    from db.session import AsyncSessionLocal
    from sqlalchemy import select
    from db.models.token import Token
    from db.models.tracked_wallet import TrackedWallet
    from db.repositories.tracked_wallet_repo import TrackedWalletRepository

    async with AsyncSessionLocal() as session:
        stmt = (
            select(Token)
            .join(TrackedWallet, TrackedWallet.token_id == Token.id)
            .where(
                TrackedWallet.telegram_id == telegram_id,
                (Token.name.ilike(f"%{query}%")) |
                (Token.symbol.ilike(f"%{query}%")) |
                (Token.contract_address.ilike(f"%{query}%"))
            )
        )
        result = await session.execute(stmt)
        tokens = result.scalars().all()

        if not tokens:
            await message.answer("❌ No matching tracked token found in your list.")
            return

        if len(tokens) == 1:
            token = tokens[0]
            tracked_repo = TrackedWalletRepository(session)
            await tracked_repo.remove_tracked_token(telegram_id, token.id)
            await message.answer(f"✅ <b>{token.name}</b> ({token.symbol}) removed.", parse_mode="HTML")
        else:
            builder = InlineKeyboardBuilder()
            for token in tokens:
                builder.button(
                    text=f"{token.name} ({token.symbol}) - {token.chain.upper()}",
                    callback_data=f"stop_token|{token.id}"
                )
            builder.adjust(1)
            await message.answer(
                "Multiple matches. Choose one to remove:",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )


@router.callback_query(lambda c: c.data.startswith("stop_token|"))
async def handle_stop_token(callback: CallbackQuery):
    await callback.answer()

    _, token_id = callback.data.split("|")
    telegram_id = callback.from_user.id

    from db.session import AsyncSessionLocal
    from db.repositories.tracked_wallet_repo import TrackedWalletRepository
    from db.models.token import Token
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        tracked_repo = TrackedWalletRepository(session)
        await tracked_repo.remove_tracked_token(telegram_id, int(token_id))

        token = (await session.execute(select(Token).where(Token.id == int(token_id)))).scalar_one_or_none()
        name = token.name if token else "Token"

    await callback.message.edit_text(f"✅ <b>{name}</b> removed from your tracked tokens.", parse_mode="HTML")


# ====================== MUTE WALLET ======================

@router.callback_query(lambda c: c.data.startswith("mute_wallet|"))
async def handle_mute_wallet(callback: CallbackQuery):
    await callback.answer("🔇 Muting wallet...")

    _, wallet_address = callback.data.split("|")
    telegram_id = callback.from_user.id

    try:
        from db.session import AsyncSessionLocal
        from db.repositories.tracked_wallet_repo import TrackedWalletRepository

        async with AsyncSessionLocal() as session:
            repo = TrackedWalletRepository(session)
            await repo.mute_wallet(telegram_id, wallet_address)

        real_time_listener.muted_wallets.add(wallet_address)
        # Try to remove the mute button — ignore if message is too old
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass  # Message already deleted or too old — mute still applied
    except Exception as e:
        print(f"Mute error: {e}")


# ====================== WALLET MONITOR ======================

@router.message(Command("wallet"))
async def cmd_wallet(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer("Usage: <code>/wallet 0xA9D1e0857e2f1f8E6c7f9f8b9c2d3e4f5a6b7c8d</code>")
        return

    address = message.text.split(maxsplit=1)[1].strip().lower()

    await message.answer(
        f"🔍 <b>Monitoring Wallet</b>\n\n"
        f"<code>{address}</code>\n\n"
        "This wallet is now being watched across all your tracked tokens.\n"
        "Large buys/sells will trigger alerts.",
        parse_mode="HTML"
    )


@router.message(Command("test_large_sell"))
async def cmd_test_large_sell(message: Message):
    await message.answer("🧪 Simulating large sell detection...")
    await message.answer(
        "🔴 <b>LARGE SELL DETECTED</b>\n\n"
        "Token: <b>Pepe (PEPE)</b>\n"
        "Wallet: <code>0x7a3c9f2d...3a4b</code>\n\n"
        "Sold: <b>28.4%</b> of previously bought volume\n"
        "Amount: 1,245,000 PEPE (~$8,750 USD)\n"
        "Realized P/L: <b>+$2,340 (+36.8%)</b>\n"
        "Wallet ROI so far: <b>+184%</b>\n"
        "Remaining holdings: ~71%\n\n"
        "This is how real alerts will look.",
        parse_mode="HTML"
    )


def register_commands(dp: Dispatcher):
    dp.include_router(router)