from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram import Dispatcher   # ← Added

router = Router()

@router.callback_query()
async def handle_all_callbacks(callback: CallbackQuery):
    await callback.answer("This feature is coming soon!", show_alert=False)

def register_callbacks(dp: Dispatcher):
    dp.include_router(router)