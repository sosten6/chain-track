from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from core.services.token_resolver import TokenInfo
from typing import List

# In-memory store mapping short key → full address
# This avoids Telegram's ~64 byte callback_data limit
_token_address_cache: dict[str, str] = {}

def build_token_selection_keyboard(tokens: List[TokenInfo]) -> InlineKeyboardMarkup:
    """Create inline buttons — stores full address in cache, passes short key in callback."""
    builder = InlineKeyboardBuilder()

    for token in tokens[:4]:  # Limit to 4 to keep it clean
        verified = " ✅" if token.is_verified else ""
        chain_short = token.chain.upper()[:3]  # ETH, SOL, BSC, etc.

        text = f"{token.symbol} ({chain_short}){verified} — ${token.liquidity_usd:,.0f}"

        # Use last 12 chars of address as a short unique key
        short_key = token.address[-12:]
        _token_address_cache[short_key] = token.address  # store full address

        # callback_data stays short: "select_token|ETH|abc123def456"
        callback_data = f"select_token|{token.chain[:3]}|{short_key}"

        builder.button(text=text, callback_data=callback_data)

    builder.adjust(1)
    return builder.as_markup()


def resolve_token_address(short_key: str) -> str | None:
    """Look up full contract address from short key."""
    return _token_address_cache.get(short_key)