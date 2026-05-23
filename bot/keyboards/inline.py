from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.services.token_resolver import TokenInfo
from typing import List

def build_token_selection_keyboard(tokens: List[TokenInfo]) -> InlineKeyboardMarkup:
    """Create inline buttons with short callback data"""
    builder = InlineKeyboardBuilder()
    
    for token in tokens[:4]:  # Limit to 4 to keep it clean
        verified = " ✅" if token.is_verified else ""
        chain_short = token.chain.upper()[:3]  # ETH, SOL, BSC, etc.
        
        # Short text for button
        text = f"{token.symbol} ({chain_short}){verified} — ${token.liquidity_usd:,.0f}"
        
        # Short callback data: "st|chain|address" (st = select_token)
        callback_data = f"select_token|{token.chain[:3]}|{token.address[:20]}"   # Max ~60 chars

        builder.button(text=text, callback_data=callback_data)
    
    builder.adjust(1)
    return builder.as_markup()