import argparse
import asyncio
import getpass
import secrets
import sys
from pathlib import Path


def cmd_check(_args) -> int:
    from .core.config import get_settings
    from .services.payments import readiness

    s = get_settings()
    print(f'Режим: {s.environment}')
    problems = s.problems()
    for p in problems:
        print('  ✗', p)
    if not problems:
        print('  ✓ секреты и администратор настроены')
    print(f'Почта: {s.email_backend}' + (' (письма не отправляются — только в лог)' if s.email_backend != 'smtp' else ''))
    print('Оплата:')
    for m in readiness(s):
        state = ('готов' if not m['missing'] else 'не хватает: ' + ', '.join(m['missing'])) if m['enabled'] else 'выключен'
        print(f"  {m['code']:15} {state}")
    return 1 if problems and s.is_production else 0


def cmd_hash_password(_args) -> int:
    from .core.security import hash_password

    pwd = getpass.getpass('Пароль администратора: ')
    if pwd != getpass.getpass('Ещё раз: '):
        print('Пароли не совпадают', file=sys.stderr)
        return 1
    if len(pwd) < 12:
        print('Нужен пароль не короче 12 символов', file=sys.stderr)
        return 1
    print('\nДобавьте в deploy/.env (а ADMIN_PASSWORD оставьте пустым):\n')
    print("ADMIN_PASSWORD_HASH='" + hash_password(pwd) + "'")
    return 0


def cmd_secret(_args) -> int:
    print('SECRET_KEY=' + secrets.token_urlsafe(48))
    return 0


def cmd_seed(args) -> int:
    from .services.seed import default_frontend, seed

    asyncio.run(seed(Path(args.frontend) if args.frontend else default_frontend()))
    return 0


def cmd_admin(_args) -> int:
    from .lifecycle import ensure_admin

    asyncio.run(ensure_admin())
    print('Готово')
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog='python -m app.cli', description='Служебные команды бэкенда магазина')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='проверить настройки .env').set_defaults(fn=cmd_check)
    sub.add_parser('hash-password', help='хеш пароля администратора для ADMIN_PASSWORD_HASH').set_defaults(fn=cmd_hash_password)
    sub.add_parser('secret', help='сгенерировать SECRET_KEY').set_defaults(fn=cmd_secret)
    sub.add_parser('admin', help='создать/обновить администратора из .env').set_defaults(fn=cmd_admin)
    p = sub.add_parser('seed', help='стартовое наполнение базы')
    p.add_argument('--frontend', default='', help='папка фронтенда (по умолчанию — рядом с backend/)')
    p.set_defaults(fn=cmd_seed)
    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == '__main__':
    main()
