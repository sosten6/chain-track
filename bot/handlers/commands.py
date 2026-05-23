from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram import Dispatcher
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.services.token_resolver import TokenResolver
from bot.keyboards.inline import build_token_selection_keyboard
from core.services.wallet_discovery import wallet_discovery
from core.services.real_time_listener import real_time_listener
from core.services.analytics import AnalyticsEngine

router = Router()

# Simple cache to normalize user ID
user_id_cache = {}

@router.message(Command("start"))
async def cmd_start(message: Message):
    telegram_id = message.chat.id
    user_id_cache[telegram_id] = telegram_id

    await message.answer(
        f"<b>🚀 SmartChain Tracker</b>\n\n"
        f"Your detected ID: <code>{telegram_id}</code>\n\n"
        "Real-time smart money tracking with price, market cap & large sell detection.\n\n"
        "Commands:\n"
        "/track &lt;token or CA&gt; — Track a token\n"
        "/list — Your tracked tokens\n"
        "/roi &lt;token&gt; — Top wallets by ROI\n"
        "/score &lt;token&gt; — Top wallets by score\n"
        "/stop &lt;token or CA&gt; — Remove tracked token\n"
        "/test_large_sell — Test alert\n"
        "/status — Bot status\n\n"
        "<i>Free tier • Smart wallet alerts enabled</i>",
        parse_mode="HTML"
    )

@router.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer("✅ Bot is running on free tier with real-time smart wallet alerts.", parse_mode="HTML")

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
    username = message.from_user.username or "Unknown"

    print(f"DEBUG: _track_token started for {token_info.name} | User: {telegram_id}")

    try:
        from db.session import AsyncSessionLocal
        from db.repositories.token_repo import TokenRepository
        from db.repositories.user_repo import UserRepository
        from db.repositories.tracked_wallet_repo import TrackedWalletRepository

        async with AsyncSessionLocal() as session:
            user_repo = UserRepository(session)
            token_repo = TokenRepository(session)
            tracked_repo = TrackedWalletRepository(session)

            await user_repo.get_or_create_user(telegram_id, username)
            token_info.chain = token_info.chain.upper()
            saved_token = await token_repo.get_or_create_token(token_info)
            await tracked_repo.add_tracked_token(telegram_id, saved_token.id)

            await session.commit()
            await session.refresh(saved_token)

        # Success path
        real_time_listener.add_token(saved_token.contract_address, saved_token.name)
        real_time_listener.last_message = message

        holders = await wallet_discovery.get_top_holders(saved_token.contract_address)
        smart_wallets = await wallet_discovery.identify_smart_wallets(holders, saved_token.contract_address)

        price = getattr(token_info, 'price_usd', None)
        market_cap = getattr(token_info, 'market_cap_usd', None)

        price_text = f"Current Price: ${price:,.8f}" if price else "Current Price: N/A"
        mc_text = f"Market Cap: ${market_cap:,.0f}" if market_cap else "Market Cap: N/A"

        wallet_list = "\n".join([f"• <code>{w['short']}</code> (ROI +{w['roi']}%)" for w in smart_wallets[:4]])

        await message.answer(
            f"✅ **Tracking Started Successfully!**\n\n"
            f"<b>{saved_token.name}</b> ({saved_token.symbol})\n"
            f"Chain: {saved_token.chain.upper()}\n"
            f"Liquidity: ${saved_token.liquidity_usd:,.0f}\n"
            f"{price_text}\n"
            f"{mc_text}\n\n"
            f"Monitored {len(smart_wallets)} smart wallets:\n{wallet_list}",
            parse_mode="HTML"
        )

    except Exception as e:
        print(f"ERROR in _track_token: {type(e).__name__}: {e}")
        await message.answer("⚠️ Token was tracked but some steps failed. Check /list.")

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
    _, chain, address = callback.data.split("|")
    await callback.message.edit_text("💾 Saving to your list...", parse_mode="HTML")

    try:
        from core.services.token_resolver import TokenResolver
        resolver = TokenResolver()
        results = await resolver.search_token(address)
        token_info = next((t for t in results if t.address.lower() == address.lower()), results[0])

        await _track_token(callback.message, token_info)
        await callback.answer("✅ Added!")

    except Exception as e:
        await callback.message.edit_text("❌ Failed to save token.")
        print(f"ERROR: {e}")


@router.message(Command("stop"))
async def cmd_stop(message: Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer("Usage: <code>/stop PEPE</code> or <code>/stop CA</code>")
        return

    query = message.text.split(maxsplit=1)[1].strip()
    await message.answer(f"🛑 Searching for <b>{query}</b> to remove...", parse_mode="HTML")

    from db.session import AsyncSessionLocal
    from sqlalchemy import select
    from db.models.token import Token
    from db.repositories.tracked_wallet_repo import TrackedWalletRepository

    async with AsyncSessionLocal() as session:
        stmt = select(Token).where(
            (Token.name.ilike(f"%{query}%")) | 
            (Token.symbol.ilike(f"%{query}%")) | 
            (Token.contract_address.ilike(f"%{query}%"))
        )
        result = await session.execute(stmt)
        tokens = result.scalars().all()

        if not tokens:
            await message.answer("Token not found in your list.")
            return

        if len(tokens) == 1:
            token = tokens[0]
            tracked_repo = TrackedWalletRepository(session)
            await tracked_repo.remove_tracked_token(message.chat.id, token.id)
            await message.answer(f"✅ <b>{token.name}</b> removed from your tracked tokens.", parse_mode="HTML")
        else:
            builder = InlineKeyboardBuilder()
            for token in tokens:
                builder.button(
                    text=f"{token.name} ({token.symbol}) - {token.chain.upper()}",
                    callback_data=f"stop_token|{token.id}"
                )
            builder.adjust(1)
            await message.answer("Multiple tokens found. Choose which one to remove:", 
                               reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("stop_token|"))
async def handle_stop_token(callback: CallbackQuery):
    _, token_id = callback.data.split("|")
    telegram_id = callback.from_user.id   # ← Fixed here

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
    await callback.answer("Removed!")


@router.callback_query(lambda c: c.data.startswith("mute_wallet|"))
async def handle_mute_wallet(callback: CallbackQuery):
    _, wallet_address = callback.data.split("|")
    real_time_listener.muted_wallets.add(wallet_address)
    await callback.answer(f"🔇 Wallet {wallet_address[:8]}... muted for alerts.")


@router.callback_query(lambda c: c.data.startswith("view_roi|"))
async def handle_view_roi(callback: CallbackQuery):
    _, wallet_address = callback.data.split("|")
    await callback.answer("📈 ROI details coming in full version.")


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
        "This is how real alerts will look when smart money sells big.",
        parse_mode="HTML"
    )


def register_commands(dp: Dispatcher):
    dp.include_router(router)