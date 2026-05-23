from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.tracked_wallet import TrackedWallet

class TrackedWalletRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_tracked_token(self, telegram_id: int, token_id: int):
        stmt = select(TrackedWallet).where(
            TrackedWallet.telegram_id == telegram_id,
            TrackedWallet.token_id == token_id
        )
        if (await self.session.execute(stmt)).scalar_one_or_none():
            return True

        new_entry = TrackedWallet(telegram_id=telegram_id, token_id=token_id)
        self.session.add(new_entry)
        await self.session.commit()
        await self.session.refresh(new_entry)
        return True

    async def remove_tracked_token(self, telegram_id: int, token_id: int):
        """Remove token from user's tracking list"""
        stmt = delete(TrackedWallet).where(
            TrackedWallet.telegram_id == telegram_id,
            TrackedWallet.token_id == token_id
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return True