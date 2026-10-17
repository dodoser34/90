# Бэкенд K-Beauty | C-Health

Сервер магазина на Python: FastAPI, PostgreSQL (SQLAlchemy 2, Alembic). Простыми словами — [docs/07-Бэкенд-Python.md](../docs/07-Бэкенд-Python.md).

## Свой компьютер — без настроек

Из папки `backend`:
```bash
python -m venv .venv
```
```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
```
```bash
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Сам создаётся `dev.db` (SQLite) со стартовыми категориями; товары автоматически не добавляются. Администратор `admin@demo.kz` / `admin12345`; коды из писем — в `dev-mail.log`. Примеры товаров при необходимости добавляются отдельно через `demo/seed_backend.py`.
На macOS/Linux вместо `.venv\Scripts\python` пишется `.venv/bin/python`. Подробно — [docs/02-Как-запустить.md](../docs/02-Как-запустить.md).

Тесты:
```bash
.venv\Scripts\python -m pytest
```

## Сервер

Все настройки — `deploy/.env` (образец с пояснениями — [`deploy/.env.example`](../deploy/.env.example)).
Публикация — [docs/13](../docs/13-Публикация-на-сервере.md), база — [docs/08](../docs/08-База-данных.md),
оплата — [docs/10](../docs/10-Оплата.md), безопасность — [docs/09](../docs/09-Безопасность.md).

## Команды

| Команда | Что делает |
|---|---|
| `python -m app.cli check` | показывает, что настроено и чего не хватает |
| `python -m app.cli secret` | создаёт `SECRET_KEY` |
| `python -m app.cli hash-password` | хеш пароля администратора для `ADMIN_PASSWORD_HASH` |
| `python -m app.cli seed` | стартовые категории магазина |
| `python -m app.cli admin` | применяет администратора из `.env` сейчас |

## Где что

| Папка | Что внутри |
|---|---|
| `app/core/` | настройки, пароли и токены, лимиты попыток, очистка ввода, защитные заголовки |
| `app/db/` | подключение к базе, таблицы с ограничениями |
| `app/schemas/` | проверка входящих данных |
| `app/services/` | оплата (`payments/`), письма, стартовое наполнение |
| `app/api/` | адреса `/api/…`, права доступа, формат ответов |
| `migrations/` | изменения схемы базы |
| `tests/` | Автоматические проверки API, базы, оплаты и настроек; команды и результаты — в разделе 16 |

Новая таблица или поле: изменить `app/db/models.py` → `alembic revision --autogenerate -m "что изменилось"` → проверить файл в `migrations/versions/` → `alembic upgrade head` (на сервере применяется само при запуске).

Дополнительные справочники: [версии библиотек](../docs/20-Библиотеки-и-инструменты.md), [все переменные окружения](../docs/23-Переменные-окружения.md), [маршруты и форматы API](../docs/24-API-и-форматы-данных.md).
