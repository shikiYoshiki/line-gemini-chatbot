"""
LINE Webhook のルーター。
- X-Line-Signature による署名検証
- イベントタイプに応じた処理の振り分け
- Gemini API を使ったテキスト応答
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

from config import Settings, get_settings
from gemini_client import GeminiClient
from history_store import HistoryStore

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────
# 依存オブジェクト（main.py から注入される）
# ─────────────────────────────────────────────────

_settings: Settings | None = None
_gemini: GeminiClient | None = None
_store: HistoryStore | None = None


def init_webhook(settings: Settings, gemini: GeminiClient, store: HistoryStore) -> None:
    """main.py のアプリ起動時に依存オブジェクトを登録する"""
    global _settings, _gemini, _store
    _settings = settings
    _gemini = gemini
    _store = store


# ─────────────────────────────────────────────────
# Webhook エンドポイント
# ─────────────────────────────────────────────────

@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(alias="X-Line-Signature"),
) -> dict:
    """LINE Platform からのイベントを受信する"""
    body = await request.body()

    # 署名検証
    parser = WebhookParser(_settings.line_channel_secret)
    try:
        events = parser.parse(body.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        logger.warning("Invalid LINE signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # イベントが空（疎通確認）の場合は即座に 200 を返す（仕様書 F-10）
    if not events:
        return {"status": "ok"}

    # 全イベントを順番に処理（仕様書 F-11）
    for event in events:
        await _handle_event(event)

    return {"status": "ok"}


# ─────────────────────────────────────────────────
# イベント処理
# ─────────────────────────────────────────────────

async def _handle_event(event) -> None:
    """イベントタイプに応じて処理を振り分ける"""
    if not isinstance(event, MessageEvent):
        return

    if isinstance(event.message, TextMessageContent):
        await _handle_text(event)
    else:
        # テキスト以外（スタンプ・画像など）には固定メッセージで応答（仕様書 F-02）
        await _reply(event.reply_token, "テキストメッセージのみ対応しています。")


async def _handle_text(event: MessageEvent) -> None:
    """テキストメッセージを処理する"""
    user_id = event.source.user_id
    text = event.message.text.strip()

    # /reset コマンド（仕様書 F-06）
    if text == "/reset":
        await _store.delete(user_id)
        await _reply(event.reply_token, "会話履歴をリセットしました。新しい会話を始めましょう！")
        return

    history = await _store.get(user_id)
    ai_reply , updated_history = await _gemini.chat(text, history)
    await _store.save(user_id, updated_history)
    await _reply(event.reply_token, ai_reply)



# ─────────────────────────────────────────────────
# LINE への返信
# ─────────────────────────────────────────────────

async def _reply(reply_token: str, message: str) -> None:
    """reply_token を使って LINE にテキストメッセージを返信する"""
    configuration = Configuration(access_token=_settings.line_channel_access_token)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=message)],
            )
        )
