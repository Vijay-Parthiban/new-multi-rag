from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.exceptions import app_error_handler
from apps.api.routes import directories, files, pipelines, uploads
from src.file_manager.core.errors import AppError
from src.file_manager.utils.paths import ensure_storage_layout
from src.shared.db.session import close_db
from src.shared.queue.client import close_redis
from src.shared.auth import verify_api_key


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage_layout()
    yield
    await close_redis()
    await close_db()


app = FastAPI(
    title="Ingestion API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)

app.include_router(uploads.router)
app.include_router(directories.router)
app.include_router(files.router)
app.include_router(pipelines.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
