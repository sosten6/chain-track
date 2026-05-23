from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.user import User

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, telegram_id: int, username: str = None):
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username
            )
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
        
        return user