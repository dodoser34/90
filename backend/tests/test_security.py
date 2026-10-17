import base64
import hashlib
import hmac
import json

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.core.sanitize import clean_text, safe_url
from app.core.security import password_problem
from app.db.models import Product, Session, User
from app.db.session import SessionLocal

from .conftest import ADMIN_PASSWORD, SENT, login, register_verified

PRODUCT = {'name': 'Тонер', 'brand': 'COSRX', 'category': 'k-beauty', 'price': 5000, 'stock': 5, 'images': []}


async def _product(client, admin, **extra) -> dict:
    await client.put('/api/categories', json=[{'id': 'k-beauty', 'name': 'K-Beauty', 'subs': []}], headers=admin)
    r = await client.post('/api/products', json={**PRODUCT, **extra}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


async def test_sql_injection_in_login_is_harmless(client):
    for email, password in [
        ("owner@example.com' --", 'x'),
        ('owner@example.com', "' OR '1'='1"),
        ('owner@example.com', "x'; DROP TABLE users; --"),
    ]:
        r = await client.post('/api/auth/login', json={'email': email, 'password': password})
        assert r.status_code in (401, 422), r.text
    await login(client)


async def test_sql_injection_in_url_and_query(client):
    admin = await login(client)
    await _product(client, admin)
    for key in ["' OR 1=1 --", '1; DROP TABLE products', '%27%20OR%201%3D1']:
        r = await client.get(f'/api/products/{key}')
        assert r.status_code == 404
    r = await client.get('/api/reviews', params={'productId': "' OR 1=1 --"})
    assert r.status_code == 200 and r.json() == []
    r = await client.get('/api/reviews', params={'voter': "x' OR '1'='1"})
    assert r.status_code == 422
    assert len((await client.get('/api/products')).json()) == 1


def test_control_characters_are_removed():
    assert clean_text('Ро\x00маш\x1bка\nтекст\tтаб') == 'Ромашка\nтекст\tтаб'


def test_safe_url_blocks_dangerous_schemes():
    for bad in ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'data:text/html,<script>', '//evil.com/x.png', 'vbscript:x', 'file:///etc/passwd']:
        assert not safe_url(bad), bad
    for good in ['', 'https://cdn.example.com/a.jpg', 'http://localhost:8000/media/a.png', 'assets/img/a.webp', '/media/products/a.jpg']:
        assert safe_url(good), good


async def test_site_texts_are_not_editable(client):
    admin = await login(client)
    r = await client.put('/api/site/texts', json={'edits': {'home.hero.title': '<script>alert(1)</script>'}}, headers=admin)
    assert r.status_code in (404, 405)


async def test_dangerous_image_urls_are_rejected(client):
    admin = await login(client)
    r = await client.post('/api/products', json={**PRODUCT, 'images': ['javascript:alert(1)']}, headers=admin)
    assert r.status_code == 422
    r = await client.put('/api/site/photos', json={'index': 0, 'url': 'data:image/svg+xml,<svg onload=alert(1)>'}, headers=admin)
    assert r.status_code == 422


ADMIN_ENDPOINTS = [
    ('GET', '/api/admin/users'),
    ('GET', '/api/admin/orders'),
    ('GET', '/api/admin/system'),
    ('POST', '/api/products'),
    ('PUT', '/api/categories'),
    ('PUT', '/api/site/photos'),
    ('POST', '/api/uploads'),
]


async def test_admin_endpoints_need_admin(client):
    buyer = await register_verified(client)
    for method, url in ADMIN_ENDPOINTS:
        r = await client.request(method, url, json={})
        assert r.status_code == 401, (method, url, r.status_code)
        r = await client.request(method, url, json={}, headers=buyer)
        assert r.status_code in (403, 422), (method, url, r.status_code)
        if r.status_code == 422:
            pytest.fail(f'{method} {url}: права должны проверяться (403), получено 422')


async def test_forged_and_oversized_tokens_are_rejected(client):
    for token in ['abc', 'x' * 43, 'Bearer ' + 'y' * 5000]:
        r = await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token})
        assert r.status_code == 401


async def test_user_cannot_touch_foreign_review(client):
    admin = await login(client)
    p = await _product(client, admin)
    a = await register_verified(client, 'a1@example.com')
    b = await register_verified(client, 'b1@example.com')
    r = await client.post(f'/api/products/{p["id"]}/reviews', json={'rating': 5, 'text': 'Отличный тонер, кожа мягкая'}, headers=a)
    assert r.status_code == 200, r.text
    rid = r.json()['review']['id']
    r = await client.delete(f'/api/reviews/{rid}', headers=b)
    assert r.status_code == 403
    r = await client.patch(f'/api/reviews/{rid}/status', json={'status': 'hidden'}, headers=b)
    assert r.status_code == 403


async def test_admin_role_cannot_be_obtained_or_removed(client):
    admin = await login(client)
    buyer = await register_verified(client)
    r = await client.patch('/api/auth/me', json={'name': 'Хакер', 'role': 'admin'}, headers=buyer)
    assert r.status_code in (200, 422)
    assert (await client.get('/api/auth/me', headers=buyer)).json()['role'] == 'customer'
    r = await client.request('DELETE', '/api/auth/me', json={'password': ADMIN_PASSWORD}, headers=admin)
    assert r.status_code == 403


async def test_login_bruteforce_is_limited(client):
    statuses = [
        (await client.post('/api/auth/login', json={'email': 'owner@example.com', 'password': f'wrong-{i}'})).status_code for i in range(8)
    ]
    assert statuses[:5] == [401] * 5
    assert 429 in statuses
    r = await client.post('/api/auth/login', json={'email': 'owner@example.com', 'password': 'wrong'})
    assert r.status_code == 429 and int(r.headers['retry-after']) > 0


async def test_login_limit_per_ip_across_emails(client):
    statuses = [
        (await client.post('/api/auth/login', json={'email': f'u{i}@example.com', 'password': 'wrong-pass'})).status_code for i in range(12)
    ]
    assert statuses.count(401) == 10 and statuses[-1] == 429


async def test_email_code_bruteforce_is_limited(client):
    await client.post('/api/auth/register', json={'name': 'Брут', 'email': 'brute@example.com', 'password': 'Kq7-mint-rose'})
    limiter.reset()
    codes = [(await client.post('/api/auth/verify', json={'email': 'brute@example.com', 'code': f'{i:06d}'})).status_code for i in range(6)]
    assert codes[:5] == [400] * 5 and codes[5] == 429
    limiter.reset()
    r = await client.post('/api/auth/verify', json={'email': 'brute@example.com', 'code': SENT[('brute@example.com', 'verify')]})
    assert r.status_code == 429


async def test_unknown_email_gives_same_answer(client):
    await register_verified(client, 'real@example.com')
    a = await client.post('/api/auth/password/forgot', json={'email': 'real@example.com'})
    b = await client.post('/api/auth/password/forgot', json={'email': 'nobody@example.com'})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    a = await client.post('/api/auth/login', json={'email': 'real@example.com', 'password': 'wrong-pass-1'})
    b = await client.post('/api/auth/login', json={'email': 'nobody@example.com', 'password': 'wrong-pass-1'})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_weak_passwords_rejected():
    assert password_problem('short')
    assert password_problem('12345678')
    assert password_problem('password')
    assert password_problem('aaaaaaaaaa')
    assert password_problem('anya-2024-pass', 'anya@example.com')
    assert password_problem('я' * 40)
    assert password_problem('Kq7-mint-rose') is None


async def test_password_change_kills_other_sessions(client):
    h1 = await register_verified(client, 'sess@example.com', 'Kq7-mint-rose')
    h2 = await login(client, 'sess@example.com', 'Kq7-mint-rose')
    r = await client.post('/api/auth/password/change', json={'old': 'Kq7-mint-rose', 'new': 'Zt5-lime-pear'}, headers=h1)
    assert r.status_code == 200
    assert (await client.get('/api/auth/me', headers=h1)).status_code == 200
    assert (await client.get('/api/auth/me', headers=h2)).status_code == 401


async def test_no_secrets_in_responses_or_database(client):
    admin = await login(client)
    token = admin['Authorization'][7:]
    await register_verified(client, 'leak@example.com', 'Kq7-mint-rose')
    for url in ['/api/auth/me', '/api/admin/users', '/api/admin/system', '/api/bootstrap']:
        body = (await client.get(url, headers=admin)).text
        for secret in ('$2b$', 'password_hash', ADMIN_PASSWORD, 'Kq7-mint-rose', get_settings().secret_key.get_secret_value(), token):
            assert secret not in body, (url, secret)
    async with SessionLocal() as db:
        sessions = (await db.execute(select(Session))).scalars().all()
        assert sessions and all(s.token_hash != token for s in sessions)
        assert hashlib.sha256(token.encode()).hexdigest() in {s.token_hash for s in sessions}
        user = (await db.execute(select(User).where(User.email == 'leak@example.com'))).scalars().one()
        assert user.password_hash.startswith('$2b$12$')


async def test_errors_do_not_reveal_internals(client):
    r = await client.post('/api/auth/login', content=b'{not json', headers={'Content-Type': 'application/json'})
    assert r.status_code == 422
    assert 'Traceback' not in r.text and 'sqlalchemy' not in r.text.lower()


async def test_security_headers(client):
    r = await client.get('/api/health')
    h = r.headers
    assert h['x-content-type-options'] == 'nosniff'
    assert h['x-frame-options'] == 'DENY'
    assert h['referrer-policy'] == 'no-referrer'
    assert "default-src 'none'" in h['content-security-policy']
    assert h['cache-control'] == 'no-store'


async def test_cors_only_for_allowed_sites(client):
    r = await client.options('/api/products', headers={'Origin': 'https://evil.example', 'Access-Control-Request-Method': 'POST'})
    assert r.headers.get('access-control-allow-origin') != 'https://evil.example'
    r = await client.options('/api/products', headers={'Origin': 'http://localhost:5174', 'Access-Control-Request-Method': 'POST'})
    assert r.headers.get('access-control-allow-origin') == 'http://localhost:5174'
    assert r.headers.get('access-control-allow-credentials') != 'true'


async def test_oversized_body_rejected(client):
    big = 'x' * (get_settings().max_body_kb * 1024 + 10)
    r = await client.post('/api/auth/login', content=json.dumps({'email': 'a@b.kz', 'password': big}), headers={'Content-Type': 'application/json'})
    assert r.status_code == 413


async def test_global_rate_limit(client):
    s = get_settings()
    old, s.rate_global = s.rate_global, '20/minute'
    try:
        codes = [(await client.get('/api/categories')).status_code for _ in range(25)]
    finally:
        s.rate_global = old
    assert codes[:20] == [200] * 20 and codes[-1] == 429
    assert (await client.get('/api/health')).status_code == 200


def test_forwarded_for_cannot_be_spoofed():
    from starlette.requests import Request

    from app.core.rate_limit import client_ip

    s = get_settings()
    s.trust_proxy = True
    try:
        scope = {'type': 'http', 'headers': [(b'x-forwarded-for', b'1.2.3.4, 203.0.113.9')], 'client': ('10.0.0.2', 1)}
        assert client_ip(Request(scope)) == '203.0.113.9'
    finally:
        s.trust_proxy = False


def _data_url(raw: bytes, mime='image/png') -> str:
    return f'data:{mime};base64,' + base64.b64encode(raw).decode()


async def test_upload_checks_real_file_type(client):
    admin = await login(client)
    png = bytes.fromhex('89504e470d0a1a0a') + b'\0' * 32
    r = await client.post('/api/uploads', json={'data': _data_url(png)}, headers=admin)
    assert r.status_code == 201 and r.json()['url'].endswith('.png')
    for fake in [b'<html><script>alert(1)</script></html>', b'<svg onload=alert(1)>', b'MZ\x90\x00 program']:
        r = await client.post('/api/uploads', json={'data': _data_url(fake)}, headers=admin)
        assert r.status_code == 422, fake
    r = await client.post('/api/uploads', json={'data': _data_url(png), 'folder': '../../etc'}, headers=admin)
    assert r.status_code == 422
    r = await client.post('/api/uploads', json={'data': _data_url(png, 'image/svg+xml')}, headers=admin)
    assert r.status_code == 422


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def test_kaspi_webhook_signature_amount_and_repeat(client):
    s = get_settings()
    old = s.payment_methods, s.kaspi_webhook_secret, s.kaspi_merchant_id, s.kaspi_api_key
    s.payment_methods, s.kaspi_webhook_secret = 'kaspi_transfer,cash,kaspi_pay', SecretStr('whsec-test-123')
    s.kaspi_merchant_id, s.kaspi_api_key = 'm-1', SecretStr('key')
    try:
        admin = await login(client)
        p = await _product(client, admin)
        buyer = await register_verified(client)
        order = {
            'name': 'Айгерим', 'phone': '+7 701 000 00 00', 'delivery': 'pickup', 'payment': 'kaspi_transfer',
            'items': [{'id': p['id'], 'qty': 1}],
        }
        r = await client.post('/api/orders', json=order, headers=buyer)
        assert r.status_code == 201, r.text
        o = r.json()
        url = '/api/payments/kaspi/webhook'

        body = json.dumps({'orderId': o['id'], 'status': 'paid', 'amount': o['total']}).encode()
        assert (await client.post(url, content=body, headers={'X-Signature': 'bad'})).status_code == 403
        assert (await client.post(url, content=body)).status_code == 403

        wrong = json.dumps({'orderId': o['id'], 'status': 'paid', 'amount': 1}).encode()
        r = await client.post(url, content=wrong, headers={'X-Signature': _sign(wrong, 'whsec-test-123')})
        assert r.status_code == 409

        r = await client.post(url, content=body, headers={'X-Signature': _sign(body, 'whsec-test-123')})
        assert r.status_code == 200
        mine = (await client.get('/api/orders/my', headers=buyer)).json()[0]
        assert mine['paymentStatus'] == 'paid'

        failed = json.dumps({'orderId': o['id'], 'status': 'failed'}).encode()
        r = await client.post(url, content=failed, headers={'X-Signature': _sign(failed, 'whsec-test-123')})
        assert r.status_code == 200
        assert (await client.get('/api/orders/my', headers=buyer)).json()[0]['paymentStatus'] == 'paid'
    finally:
        s.payment_methods, s.kaspi_webhook_secret, s.kaspi_merchant_id, s.kaspi_api_key = old


async def test_webhook_disabled_without_kaspi_pay(client):
    r = await client.post('/api/payments/kaspi/webhook', content=b'{}', headers={'X-Signature': 'x'})
    assert r.status_code == 404


async def test_order_amounts_cannot_be_forged(client):
    admin = await login(client)
    p = await _product(client, admin, price=7000, stock=2)
    buyer = await register_verified(client)
    order = {
        'name': 'Айгерим', 'phone': '+7 701 000 00 00', 'delivery': 'pickup', 'payment': 'cash',
        'items': [{'id': p['id'], 'qty': 50, 'price': 1}], 'total': 1, 'subtotal': 1,
    }
    r = await client.post('/api/orders', json=order, headers=buyer)
    assert r.status_code == 201
    assert r.json()['total'] == 14000
    order['payment'] = 'bitcoin'
    assert (await client.post('/api/orders', json=order, headers=buyer)).status_code in (400, 422)


def test_production_refuses_unsafe_settings():
    s = Settings(
        _env_file=None, environment='production', secret_key='change-me', admin_email='', admin_password='', database_url='',
        frontend_url='http://localhost:5174', email_backend='console', docs_enabled=None,
    )
    problems = ' '.join(s.problems())
    for name in ('SECRET_KEY', 'ADMIN_PASSWORD', 'ADMIN_EMAIL', 'DATABASE_URL', 'EMAIL_BACKEND'):
        assert name in problems, name
    assert not s.show_docs
    assert s.admin_password.get_secret_value() == ''


def test_production_accepts_good_settings():
    s = Settings(
        _env_file=None,
        environment='production',
        secret_key='Zq8vR1pLmN4wX7yB2cD5eF9gH0jK6sTuV3',
        database_url='postgres://kbch:pw@db:5432/kbch',
        admin_email='owner@gmail.com',
        admin_password='Very-Long-Owner-Pass-2026',
        frontend_url='https://shop.kz',
        public_api_url='https://shop.kz/api',
        cors_origins='https://shop.kz',
        email_backend='smtp',
        smtp_user='owner@gmail.com',
        smtp_password='test-application-password',
    )
    assert s.problems() == []
    assert s.database_url.get_secret_value().startswith('postgresql+asyncpg://')
    assert 'Very-Long' not in repr(s) and 'pw@db' not in repr(s)


async def test_admin_from_password_hash(client):
    from app.core.security import hash_password
    from app.lifecycle import ensure_admin

    s = get_settings()
    old = s.admin_password, s.admin_password_hash
    s.admin_password, s.admin_password_hash = SecretStr(''), SecretStr(hash_password('Hash-Only-Pass-99'))
    try:
        await ensure_admin()
        await login(client, 'owner@example.com', 'Hash-Only-Pass-99')
    finally:
        s.admin_password, s.admin_password_hash = old
        await ensure_admin()


async def test_products_table_untouched_by_hidden_access(client):
    admin = await login(client)
    await _product(client, admin, status='hidden')
    assert (await client.get('/api/products')).json() == []
    assert (await client.get('/api/products', params={'all': 1})).json() == []
    async with SessionLocal() as db:
        assert len((await db.execute(select(Product))).scalars().all()) == 1
