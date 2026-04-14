"""
会話履歴の読み書きを担当するモジュール。
STORE_TYPE 環境変数に応じて SQLite または Redis を使用する。

履歴フォーマット (Gemini API準拠):
  [
    {"role": "user",  "parts": [{"text": "こんにちは"}]},
    {"role": "model", "parts": [{"text": "こんにちは！..."}]},
    ...
  ]
"""

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from config import Settings

# 1ターン = user + model の2メッセージ
# MAX_HISTORY_TURNS=20 なら最大40メッセージを保持
MESSAGES_PER_TURN = 2


# ─────────────────────────────────────────────────
# 抽象基底クラス
# ─────────────────────────────────────────────────

class HistoryStore(ABC):
    """会話履歴ストアの共通インターフェース"""

    @abstractmethod
    async def get(self, user_id: str) -> list[dict]:
        """指定ユーザーの会話履歴を取得する"""

    @abstractmethod
    async def save(self, user_id: str, history: list[dict]) -> None:
        """指定ユーザーの会話履歴を保存する"""

    @abstractmethod
    async def delete(self, user_id: str) -> None:
        """指定ユーザーの会話履歴を削除する"""

    def trim(self, history: list[dict], max_turns: int) -> list[dict]:
        """古いターンを削除して最大ターン数に収める"""
        max_messages = max_turns * MESSAGES_PER_TURN
        if len(history) > max_messages:
            history = history[-max_messages:]
        return history


# ─────────────────────────────────────────────────
# SQLite 実装（ローカル開発用）
# ─────────────────────────────────────────────────

class SQLiteHistoryStore(HistoryStore):
    """SQLite を使った会話履歴ストア（開発・テスト用）"""

    DB_PATH = Path("chatbot.db")

    def __init__(self, settings: Settings) -> None:
        self.max_turns = settings.max_history_turns
        self._init_db()

    def _init_db(self) -> None:
        """テーブルが存在しない場合は作成する"""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT NOT NULL,
                    role       TEXT NOT NULL CHECK(role IN ('user', 'model')),
                    content    TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user_id
                ON conversations(user_id, created_at)
            """)

    async def get(self, user_id: str) -> list[dict]:
        max_messages = self.max_turns * MESSAGES_PER_TURN
        with sqlite3.connect(self.DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM (
                    SELECT role, content, created_at
                    FROM conversations
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ) ORDER BY created_at ASC
                """,
                (user_id, max_messages),
            ).fetchall()

        return [
            {"role": role, "parts": [{"text": content}]}
            for role, content in rows
        ]

    async def save(self, user_id: str, history: list[dict]) -> None:
        history = self.trim(history, self.max_turns)

        with sqlite3.connect(self.DB_PATH) as conn:
            # 既存履歴を削除して全件書き直し
            conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
                [
                    (user_id, msg["role"], msg["parts"][0]["text"])
                    for msg in history
                ],
            )

    async def delete(self, user_id: str) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))


# ─────────────────────────────────────────────────
# Redis 実装（本番用）
# ─────────────────────────────────────────────────

class RedisHistoryStore(HistoryStore):
    """Redis を使った会話履歴ストア（本番用）"""

    KEY_PREFIX = "conversation:"

    def __init__(self, settings: Settings) -> None:
        import redis.asyncio as aioredis
        self.client = aioredis.from_url(settings.redis_url, decode_responses=True)
        self.max_turns = settings.max_history_turns
        self.ttl = settings.history_ttl_seconds

    def _key(self, user_id: str) -> str:
        return f"{self.KEY_PREFIX}{user_id}"

    async def get(self, user_id: str) -> list[dict]:
        raw = await self.client.get(self._key(user_id))
        if raw is None:
            return []
        return json.loads(raw)

    async def save(self, user_id: str, history: list[dict]) -> None:
        history = self.trim(history, self.max_turns)
        key = self._key(user_id)
        await self.client.set(key, json.dumps(history, ensure_ascii=False))
        await self.client.expire(key, self.ttl)

    async def delete(self, user_id: str) -> None:
        await self.client.delete(self._key(user_id))


# ─────────────────────────────────────────────────
# ファクトリ関数
# ─────────────────────────────────────────────────

def create_history_store(settings: Settings) -> HistoryStore:
    """STORE_TYPE に応じたストアを返す"""
    if settings.store_type == "redis":
        return RedisHistoryStore(settings)
    return SQLiteHistoryStore(settings)
