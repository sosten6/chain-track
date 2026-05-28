import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession

from config.settings import settings
from db.session import init_db
from bot.handlers.commands import register_commands
from core.services.real_time_listener import real_time_listener

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

session = AiohttpSession(timeout=60)
bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


async def restore_tracked_tokens():
    """
    On restart, reload all tracked tokens from DB into real_time_listener
    so WebSocket subscriptions pick them up immediately.
    """
    try:
        from db.session import AsyncSessionLocal
        from sqlalchemy import select
        from db.models.token import Token
        from db.models.tracked_wallet import TrackedWallet

        async with AsyncSessionLocal() as session:
            stmt = select(Token).join(TrackedWallet, TrackedWallet.token_id == Token.id).distinct()
            result = await session.execute(stmt)
            tokens = result.scalars().all()

        for token in tokens:
            price = float(token.price_usd or 0)
            real_time_listener.tracked_tokens[token.contract_address.lower()] = token.name
            real_time_listener.tracked_chains[token.contract_address.lower()] = token.chain.lower()
            real_time_listener.tracked_prices[token.contract_address.lower()] = price
            # Kick off wallet loading in background
            asyncio.create_task(
                real_time_listener._load_smart_wallets(token.contract_address, token.chain, price)
            )

        if tokens:
            logger.info(f"♻️  Restored {len(tokens)} tracked tokens from DB")

    except Exception as e:
        logger.warning(f"Token restore failed: {e}")


async def main():
    logger.info("🚀 Starting SmartChain Tracker Bot...")

    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"Database failed: {e}")
        return

    register_commands(dp)

    # Restore tokens from DB so WS listeners have them on startup
    await restore_tracked_tokens()

    # Start real-time listeners (EVM WS + Solana WS + BSC polling)
    asyncio.create_task(real_time_listener.start())

    try:
        bot_info = await bot.get_me()
        logger.info(f"🤖 Bot live → @{bot_info.username}")
    except Exception as e:
        logger.warning(f"Bot info error: {e}")

    await dp.start_polling(bot, polling_timeout=30)


if __name__ == "__main__":
    asyncio.run(main())