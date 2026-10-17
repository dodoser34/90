import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from .core.config import get_settings
from .core.security import hash_password, verify_password
from .db.models import User
from .db.session import Base, SessionLocal, engine
from .services.seed import default_frontend, is_empty, seed

log = logging.getLogger('kbch')


async def ensure_admin() -> None:
    s = get_settings()
    email = s.admin_email.strip().lower()
    pwd, pwd_hash = s.admin_password.get_secret_value(), s.admin_password_hash.get_secret_value().strip()
    async with SessionLocal() as db:
        admin = (await db.execute(select(User).where(User.email == email))).scalars().first()
        if not admin:
            admin = User(email=email, name=s.admin_name)
            db.add(admin)
            log.info('Создан администратор %s', email)
        admin.role, admin.email_verified, admin.blocked = 'admin', True, False
        if pwd_hash.startswith('$2'):
            admin.password_hash = pwd_hash
        elif pwd and not verify_password(pwd, admin.password_hash):
            admin.password_hash = hash_password(pwd)
        elif not pwd:
            log.error('Пароль администратора не задан: укажите ADMIN_PASSWORD или ADMIN_PASSWORD_HASH в .env')
        for other in (await db.execute(select(User).where(User.role == 'admin', User.email != email))).scalars().all():
            other.role = 'customer'
        await db.commit()


def check_settings() -> None:
    s = get_settings()
    problems = s.problems()
    if problems and s.is_production:
        raise RuntimeError('Небезопасные настройки .env:\n  - ' + '\n  - '.join(problems))
    if not s.is_production:
        log.info('Локальный режим (development): база %s, администратор %s', 'SQLite dev.db' if s.is_sqlite else 'PostgreSQL', s.admin_email)
        if problems:
            log.info('Для сервера нужно будет настроить: %s', '; '.join(p.split(':')[0] for p in problems))


async def prepare_dev_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if await is_empty():
        try:
            await seed(default_frontend())
        except (OSError, SystemExit, ValueError):
            log.warning('Начальные категории пропущены: не найдена папка фронтенда')


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_settings()
    s = get_settings()
    if not s.is_production and s.is_sqlite and s.auto_create_tables:
        await prepare_dev_database()
    try:
        await ensure_admin()
    except Exception:
        log.exception('Не удалось создать администратора. Выполнены ли миграции (alembic upgrade head)?')
        if s.is_production:
            raise RuntimeError('Не удалось подготовить базу данных и администратора')
    try:
        yield
    finally:
        await engine.dispose()


