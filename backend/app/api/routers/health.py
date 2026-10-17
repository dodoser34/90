import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db

router = APIRouter()
log = logging.getLogger('kbch')


@router.get('/health', tags=['Сервис'], summary='Проверка, что сервер работает')
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.scalar(select(1))
    except Exception as exc:
        log.exception('Проверка готовности: база данных недоступна')
        raise HTTPException(503, 'База данных недоступна') from exc
    return {'status': 'ok'}
