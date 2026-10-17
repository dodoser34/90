import pytest

from app import lifecycle, main
from app.core.config import Settings
from app.db.session import get_db


def production_settings(**changes):
    return Settings(
        _env_file=None,
        **{
            'environment': 'production',
            'secret_key': 'Zq8vR1pLmN4wX7yB2cD5eF9gH0jK6sTuV3',
            'database_url': 'postgresql+asyncpg://test:pw@db:5432/test',
            'admin_email': 'owner@shop.kz',
            'admin_password': 'Very-Long-Owner-Pass-2026',
            'frontend_url': 'https://shop.kz',
            'public_api_url': 'https://shop.kz/api',
            'cors_origins': 'https://shop.kz',
            'payment_methods': 'cash',
            'email_backend': 'smtp',
            'smtp_host': 'smtp.gmail.com',
            'smtp_port': 587,
            'smtp_user': 'owner@shop.kz',
            'smtp_password': 'application-password',
            'smtp_from': 'Shop <owner@shop.kz>',
            **changes,
        },
    )


@pytest.mark.parametrize('changes,required', [
    ({'smtp_host': ''}, 'SMTP_HOST'),
    ({'smtp_port': 0}, 'SMTP_PORT'),
    ({'smtp_port': 65536}, 'SMTP_PORT'),
    ({'smtp_user': '', 'smtp_password': '', 'smtp_from': ''}, 'SMTP_FROM'),
    ({'smtp_password': ''}, 'SMTP_PASSWORD'),
    ({'smtp_user': ''}, 'SMTP_USER'),
    ({'smtp_user': '', 'smtp_password': ''}, 'SMTP_PASSWORD'),
])


def test_production_rejects_incomplete_smtp_settings(changes, required):
    assert required in ' '.join(production_settings(**changes).problems())


def test_production_supports_explicit_anonymous_smtp_relay():
    assert production_settings(smtp_host='relay.internal', smtp_user='', smtp_password='').problems() == []


@pytest.mark.asyncio
async def test_production_startup_fails_if_admin_database_initialization_fails(monkeypatch):
    monkeypatch.setattr(lifecycle, 'get_settings', production_settings)

    async def unavailable():
        raise RuntimeError('test database unavailable')

    monkeypatch.setattr(lifecycle, 'ensure_admin', unavailable)
    with pytest.raises(RuntimeError, match='подготовить базу данных'):
        async with lifecycle.lifespan(main.app):
            pytest.fail('production must not start with an unavailable database')


@pytest.mark.asyncio
async def test_health_returns_503_when_database_becomes_unavailable(client):
    class UnavailableDatabase:
        async def scalar(self, _query):
            raise RuntimeError('private-database-password')

    async def unavailable_db():
        yield UnavailableDatabase()

    main.app.dependency_overrides[get_db] = unavailable_db
    try:
        response = await client.get('/api/health')
        assert response.status_code == 503
        assert response.json() == {'detail': 'База данных недоступна'}
        assert 'private-database-password' not in response.text
    finally:
        main.app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_health_returns_200_after_database_recovers(client):
    response = await client.get('/api/health')
    assert response.status_code == 200 and response.json() == {'status': 'ok'}
