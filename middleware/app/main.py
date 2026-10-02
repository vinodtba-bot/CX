import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import init_db
from .routers import admin, demo, retell, widget
from .services.facets import get_facets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.retell_api_key and not settings.allow_unsigned_retell:
        logging.warning("RETELL_API_KEY is not set: Retell endpoints will reject requests")
    if settings.allow_unsigned_retell:
        logging.warning("ALLOW_UNSIGNED_RETELL is on. Local development only.")
    await init_db()
    yield
    await get_facets().aclose()


app = FastAPI(title="Payer AI Middleware", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(retell.router)
app.include_router(widget.router)
app.include_router(admin.router)
app.include_router(demo.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
