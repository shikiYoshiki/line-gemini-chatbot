"""
Google Gemini API との通信を担当するモジュール。
会話履歴を渡してテキスト応答を生成する。
"""

import asyncio
import logging

import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

from config import Settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """Gemini API クライアント"""

    ERROR_MESSAGE = "申し訳ありません、応答を取得できませんでした。しばらくしてからもう一度お試しください。"

    def __init__(self, settings: Settings) -> None:
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(model_name=settings.gemini_model)
        logger.info("GeminiClient initialized: model=%s", settings.gemini_model)

    async def chat(self, user_message: str, history: list[dict]) -> tuple[str, list[dict]]:
        """
        ユーザーメッセージを送信し、AI応答と更新された履歴を返す。

        Args:
            user_message: ユーザーの発言テキスト
            history:      これまでの会話履歴 (Gemini API フォーマット)

        Returns:
            (ai_reply, updated_history)
            - ai_reply:       AIの返答テキスト
            - updated_history: 今回のやり取りを追記した履歴
        """
        try:
            ai_reply = await asyncio.to_thread(
                self._send_message, user_message, history
            )
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            return self.ERROR_MESSAGE, history

        updated_history = history + [
            {"role": "user",  "parts": [{"text": user_message}]},
            {"role": "model", "parts": [{"text": ai_reply}]},
        ]
        return ai_reply, updated_history

    def _send_message(self, user_message: str, history: list[dict]) -> str:
        """同期処理: Gemini API を呼び出してテキストを返す（to_thread で実行）"""
        chat_session = self.model.start_chat(history=history)
        response: GenerateContentResponse = chat_session.send_message(user_message)
        return response.text
