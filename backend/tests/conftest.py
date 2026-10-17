import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=os.environ.get('TEST_DATABASE_URL') or f'sqlite+aiosqlite:///{_tmp}/test.db',
    MEDIA_DIR=f'{_tmp}/media',
    SECRET_KEY='t3st-k3y-Zq8vR1pLmN4wX7yB2cD5eF9gH0jK6sT',
    ADMIN_EMAIL='owner@example.com',
    ADMIN_PASSWORD='Owner-Strong-Pass-71',
    KASPI_PHONE='+7 700 000 00 00',
    KASPI_RECEIVER='Наргиз К.',
    PAYMENT_METHODS='kaspi_transfer,cash',
    CODE_RESEND_SECONDS='0',
    EMAIL_BACKEND='console',
    ENVIRONMENT='development',
    DOCS_ENABLED='true',
)


import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.api.routers import auth as auth_router
from app.core.rate_limit import limiter
from app.db.session import Base, engine
from app.main import app
from app.lifecycle import ensure_admin
from app.services import emails

ADMIN_PASSWORD = 'Owner-Strong-Pass-71'

if engine.dialect.name == 'sqlite':

    @event.listens_for(engine.sync_engine, 'connect')
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute('PRAGMA foreign_keys=ON')


SENT: dict[tuple[str, str], str] = {}


async def _fake_send(email: str, code: str, purpose: str) -> None:
    SENT[(email, purpose)] = code


emails.send_code = _fake_send
auth_router.send_code = _fake_send


@pytest_asyncio.fixture(loop_scope='function')
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    SENT.clear()
    limiter.reset()
    await ensure_admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
            yield c
    finally:
        await engine.dispose()


async def login(client, email='owner@example.com', password=ADMIN_PASSWORD) -> dict:
    r = await client.post('/api/auth/login', json={'email': email, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


async def register_verified(client, email='buyer@example.com', password='Kq7-mint-rose', name='Айгерим') -> dict:
    r = await client.post('/api/auth/register', json={'name': name, 'email': email, 'password': password})
    assert r.status_code == 200, r.text
    r = await client.post('/api/auth/verify', json={'email': email, 'code': SENT[(email, 'verify')]})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}
