"""
FastAPI アプリのエントリーポイント。
起動時に各コンポーネントを初期化し、ルーターを登録する。
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from config import get_settings
from gemini_client import GeminiClient
from history_store import create_history_store
from webhook import init_webhook, router as webhook_router


def setup_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動・終了時の処理"""
    settings = get_settings()
    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info("Starting chatbot server...")

    gemini = GeminiClient(settings)
    store = create_history_store(settings)
    init_webhook(settings, gemini, store)

    logger.info("All components initialized. store_type=%s", settings.store_type)

    yield  # ← ここでサーバーが起動し、リクエストを受け付ける

    logger.info("Shutting down chatbot server.")


app = FastAPI(title="LINE × Gemini Chatbot", lifespan=lifespan)

app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict:
    """サービスの生存確認エンドポイント（仕様書 §6）"""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
