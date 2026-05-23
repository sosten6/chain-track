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

async def main():
    logger.info("🚀 Starting SmartChain Tracker Bot...")

    try:
        await init_db()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"Database failed: {e}")
        return

    register_commands(dp)

    # Start real WebSocket listener
    asyncio.create_task(real_time_listener.start())

    try:
        bot_info = await bot.get_me()
        logger.info(f"🤖 Bot live → @{bot_info.username}")
    except Exception as e:
        logger.warning(f"Bot info error: {e}")

    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())