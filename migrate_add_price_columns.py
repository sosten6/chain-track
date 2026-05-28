"""
One-time migration: adds price_usd and market_cap_usd columns to the tokens table.
Run once with: python migrate_add_price_columns.py
"""
import asyncio
from db.session import engine

async def migrate():
    async with engine.begin() as conn:
        # Add columns only if they don't exist (safe to re-run)
        await conn.execute(__import__('sqlalchemy').text("""
            ALTER TABLE tokens
            ADD COLUMN IF NOT EXISTS price_usd FLOAT DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS market_cap_usd FLOAT DEFAULT 0.0;
        """))
        print("✅ Migration complete — price_usd and market_cap_usd added to tokens table")

if __name__ == "__main__":
    asyncio.run(migrate())