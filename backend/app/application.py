import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.routers import auth, catalog, health, orders, reviews, site
from .core.config import get_settings
from .core.middleware import install as install_security
from .lifecycle import lifespan

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f'{s.app_name} — API',
        version='1.1.0',
        docs_url='/api/docs' if s.show_docs else None,
        redoc_url=None,
        openapi_url='/api/openapi.json' if s.show_docs else None,
        lifespan=lifespan,
    )
    install_security(app)
    if s.cors_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_list,
            allow_credentials=False,
            allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
            allow_headers=['Authorization', 'Content-Type'],
            max_age=600,
        )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.hosts_list)

    for r in (auth, catalog, reviews, orders, site, health):
        app.include_router(r.router, prefix='/api')

    Path(s.media_dir).mkdir(parents=True, exist_ok=True)
    app.mount(s.media_url, StaticFiles(directory=s.media_dir), name='media')
    return app

