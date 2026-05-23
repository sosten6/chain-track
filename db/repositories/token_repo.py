from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.token import Token
from core.services.token_resolver import TokenInfo

class TokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_token(self, token_info: TokenInfo) -> Token:
        """Get existing token or create new one"""
        stmt = select(Token).where(Token.contract_address == token_info.address)
        result = await self.session.execute(stmt)
        token = result.scalar_one_or_none()

        if token:
            # Update liquidity if newer
            if token_info.liquidity_usd > token.liquidity_usd:
                token.liquidity_usd = token_info.liquidity_usd
                token.last_metadata_update = token_info.last_metadata_update if hasattr(token_info, 'last_metadata_update') else None
            return token

        # Create new token
        new_token = Token(
            chain=token_info.chain.lower(),
            contract_address=token_info.address,
            name=token_info.name,
            symbol=token_info.symbol,
            liquidity_usd=token_info.liquidity_usd,
            is_verified=token_info.is_verified
        )
        self.session.add(new_token)
        await self.session.commit()
        await self.session.refresh(new_token)
        return new_token