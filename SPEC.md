# LINE × Gemini API Chatbot 仕様書

**バージョン**: 1.0.0  
**作成日**: 2026-04-14  
**ステータス**: ドラフト

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [システムアーキテクチャ](#2-システムアーキテクチャ)
3. [機能要件](#3-機能要件)
4. [非機能要件](#4-非機能要件)
5. [技術スタック](#5-技術スタック)
6. [APIエンドポイント設計](#6-apiエンドポイント設計)
7. [データモデル](#7-データモデル)
8. [環境変数](#8-環境変数)
9. [セキュリティ要件](#9-セキュリティ要件)
10. [デプロイ構成](#10-デプロイ構成)
11. [今後の拡張候補](#11-今後の拡張候補)

---

## 1. プロジェクト概要

### 目的

LINE上で動作する汎用AIチャットボットを開発する。ユーザーはLINEアプリを通じて自然言語でAIと会話でき、Google Gemini APIが応答を生成する。

### スコープ

| 項目 | 内容 |
|------|------|
| 対象プラットフォーム | LINE (Messaging API) |
| AIモデル | Google Gemini API |
| 主要機能 | 汎用会話 (Q&A)、会話履歴の維持 |
| 対象ユーザー | LINEアカウントを持つ個人ユーザー |

### スコープ外

- Web/モバイルアプリのUI開発
- WhatsApp / Slack などLINE以外のプラットフォーム対応
- 画像・音声・ファイルの処理（将来拡張候補）
- ユーザー管理・認証機能

### 用語定義

| 用語 | 説明 |
|------|------|
| Webhook | LINE PlatformからサーバーへのHTTPS POSTリクエスト |
| reply_token | LINEが発行する1回限りの返信用トークン（30秒有効） |
| ユーザーID | LINEが各ユーザーに割り当てる一意のID (`U` で始まる文字列) |
| ターン | ユーザー発言1回 + AI返答1回のセット |

---

## 2. システムアーキテクチャ

### 全体構成図

```
┌─────────────────────────────────────────────────┐
│                  LINEユーザー                    │
│         (iPhoneアプリ / Androidアプリ)           │
└────────────────────┬────────────────────────────┘
                     │ メッセージ送信
                     ▼
┌─────────────────────────────────────────────────┐
│              LINE Platform                       │
│         (LINE Messaging API)                     │
└────────────────────┬────────────────────────────┘
                     │ Webhook (HTTPS POST /webhook)
                     ▼
┌─────────────────────────────────────────────────┐
│           Chatbot Backend Server                 │
│               (FastAPI / Python)                 │
│                                                  │
│  1. LINE署名の検証                               │
│  2. イベントタイプの解析                         │
│  3. 会話履歴の取得                               │
│  4. Gemini APIへのリクエスト                     │
│  5. 履歴の更新・保存                             │
│  6. LINEへの返信送信                             │
└──────┬────────────────────────┬─────────────────┘
       │                        │
       ▼                        ▼
┌─────────────┐       ┌─────────────────────────┐
│  データストア │       │      Google Gemini API   │
│(Redis/SQLite)│       │   (gemini-1.5-flash)     │
│             │       │                          │
│ 会話履歴保存 │       │  AI応答生成              │
└─────────────┘       └─────────────────────────┘
```

### シーケンス図

```
ユーザー    LINE Platform    Backend Server    データストア    Gemini API
   │              │                │                │              │
   │─メッセージ──▶│                │                │              │
   │              │─Webhook POST──▶│                │              │
   │              │                │─履歴取得──────▶│              │
   │              │                │◀──会話履歴─────│              │
   │              │                │─会話履歴付きリクエスト────────▶│
   │              │                │◀──────────────────────AI応答──│
   │              │                │─履歴保存──────▶│              │
   │              │◀─reply_tokenで返信─│            │              │
   │◀─AI返答──────│                │                │              │
```

---

## 3. 機能要件

### 3.1 メッセージ応答機能

| ID | 要件 | 優先度 |
|----|------|--------|
| F-01 | テキストメッセージを受信し、Gemini APIを使って自然な返答を生成・送信する | 必須 |
| F-02 | スタンプ・画像などテキスト以外のメッセージには固定のテキストで応答する | 必須 |
| F-03 | Gemini APIエラー時は「応答を取得できませんでした」旨のメッセージを返す | 必須 |

### 3.2 会話履歴管理

| ID | 要件 | 優先度 |
|----|------|--------|
| F-04 | ユーザーIDをキーとして、直近の会話履歴をデータストアに保持する | 必須 |
| F-05 | 会話履歴は最大 **20ターン**（40メッセージ）まで保持し、超過分は古いものから削除する | 必須 |
| F-06 | ユーザーが `/reset` と送信すると会話履歴をリセットし、確認メッセージを返す | 必須 |
| F-07 | 会話履歴のTTLは **24時間** とし、非活動ユーザーのデータを自動削除する | 推奨 |

### 3.3 Webhook処理

| ID | 要件 | 優先度 |
|----|------|--------|
| F-08 | LINE Platformからのリクエストに含まれる署名（`X-Line-Signature`ヘッダー）を検証する | 必須 |
| F-09 | 署名検証に失敗した場合は `403 Forbidden` を返す | 必須 |
| F-10 | LINE PlatformからのWebhook疎通確認（空イベント）には即座に `200 OK` を返す | 必須 |
| F-11 | 複数イベントが同時に届いた場合（バッチ送信）、全イベントを順番に処理する | 必須 |

---

## 4. 非機能要件

### 4.1 パフォーマンス

| 項目 | 目標値 | 備考 |
|------|--------|------|
| Webhook応答時間 | **30秒以内** | LINE Platformのタイムアウト制約 |
| Gemini API呼び出し含む全処理 | **10秒以内** | ユーザー体験の観点 |

### 4.2 可用性

| 項目 | 目標値 |
|------|--------|
| サービス稼働率 | 99%以上（月間） |
| 計画外ダウンタイム | 月間 7時間以内 |

### 4.3 スケーラビリティ

- 初期フェーズは単一インスタンス構成
- 将来的な水平スケールに備え、セッション状態はサーバー外部（Redis等）で管理する

### 4.4 保守性

- 環境変数で設定を外部化し、コード変更なしに設定変更できる
- ログにリクエスト/レスポンスの概要を記録し、問題の追跡を容易にする

---

## 5. 技術スタック

| レイヤー | 技術 | バージョン | 選定理由 |
|---------|------|-----------|---------|
| プログラミング言語 | Python | 3.11+ | Gemini SDK・LINE SDK が充実。AI開発エコシステムが豊富 |
| Webフレームワーク | FastAPI | 0.110+ | 非同期対応・型安全・自動ドキュメント生成 |
| LINE SDK | line-bot-sdk-python | 3.x | 署名検証・メッセージ送受信を簡略化 |
| AI SDK | google-generativeai | 0.7+ | Gemini APIの公式Pythonクライアント |
| 会話履歴ストア | Redis | 7.x | 高速なKVS、TTL設定が容易（本番向け） |
| 会話履歴ストア（開発） | SQLite + JSON | 標準ライブラリ | ローカル開発時の依存関係を最小化 |
| 依存管理 | uv または pip | 最新 | パッケージ管理 |
| ローカルトンネル | ngrok | 最新 | ローカル開発時のWebhook受信 |

### Gemini モデル選定

| モデル | 用途 | 選定理由 |
|--------|------|---------|
| `gemini-1.5-flash` | 本番・デフォルト | 高速・低コスト、会話用途に最適 |
| `gemini-1.5-pro` | 複雑な質問への対応 | 精度優先の場合に切り替え可能 |

---

## 6. APIエンドポイント設計

### POST /webhook

LINE Platformからのイベントを受信する。

**リクエストヘッダー**

```
X-Line-Signature: <HMAC-SHA256署名 (Base64)>
Content-Type: application/json
```

**リクエストボディ**（LINE Platform仕様に準拠）

```json
{
  "destination": "Uxxxxxxxxxx",
  "events": [
    {
      "type": "message",
      "message": {
        "type": "text",
        "id": "xxxxxxxx",
        "text": "こんにちは"
      },
      "replyToken": "xxxxxxxxxxxxxxxxxxxxxxxx",
      "source": {
        "type": "user",
        "userId": "Uxxxxxxxxxx"
      },
      "timestamp": 1713024000000
    }
  ]
}
```

**レスポンス**

| ステータス | 条件 |
|-----------|------|
| `200 OK` | 正常処理完了（LINE仕様上、常に200を返す必要あり） |
| `403 Forbidden` | 署名検証失敗 |

---

### GET /health

サービスの生存確認用エンドポイント。

**レスポンス**

```json
{
  "status": "ok",
  "timestamp": "2026-04-14T00:00:00Z"
}
```

---

## 7. データモデル

### 会話履歴（Redisの場合）

```
キー: conversation:{line_user_id}
型:   String (JSON配列)
TTL:  86400秒 (24時間)
```

**JSON構造**

```json
[
  {
    "role": "user",
    "parts": [{"text": "Pythonとは何ですか？"}]
  },
  {
    "role": "model",
    "parts": [{"text": "Pythonは汎用プログラミング言語で..."}]
  }
]
```

> **Note**: `role` と `parts` のフォーマットは Gemini API の `ChatSession` 形式に準拠。

### 会話履歴（SQLiteの場合）

```sql
CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('user', 'model')),
    content     TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_conversations_user_id ON conversations(user_id, created_at);
```

---

## 8. 環境変数

`.env` ファイルまたはクラウドの環境変数設定で管理する。**コードにハードコードしない。**

```env
# LINE Messaging API
LINE_CHANNEL_SECRET=<LINEコンソールから取得>
LINE_CHANNEL_ACCESS_TOKEN=<LINEコンソールから取得>

# Google Gemini API
GEMINI_API_KEY=<Google AI Studioから取得>
GEMINI_MODEL=gemini-1.5-flash

# データストア
STORE_TYPE=redis          # "redis" or "sqlite"
REDIS_URL=redis://localhost:6379/0

# アプリ設定
MAX_HISTORY_TURNS=20      # 保持する会話ターン数の上限
HISTORY_TTL_SECONDS=86400 # 会話履歴のTTL (秒)
LOG_LEVEL=INFO
```

---

## 9. セキュリティ要件

### 9.1 LINE署名検証

すべての `/webhook` リクエストで以下を検証する:

1. `X-Line-Signature` ヘッダーの存在確認
2. `LINE_CHANNEL_SECRET` を使ったHMAC-SHA256でリクエストボディを署名
3. ヘッダーの値と計算した署名をBase64比較
4. 不一致の場合は `403 Forbidden` を返し、以降の処理を行わない

### 9.2 シークレット管理

- APIキー・シークレットは環境変数で管理
- `.env` ファイルは `.gitignore` に追加し、Gitリポジトリにコミットしない
- `.env.example` ファイルを用意し、必要な環境変数名のみを記載する

### 9.3 通信

- HTTPS必須（デプロイ先のクラウドサービスで自動対応）
- LINE Platformへの返信も公式SDK経由でHTTPS通信

---

## 10. デプロイ構成

### 推奨デプロイ先

| サービス | 特徴 | 備考 |
|---------|------|------|
| **Railway** | 無料枠あり、Redis内蔵、HTTPS自動 | 最初の選択肢として推奨 |
| **Render** | 無料枠あり、HTTPS自動 | Redisは別途アドオン |
| **GCP Cloud Run** | サーバーレス、スケーラブル | 無料枠あり、本番拡張向け |

### ローカル開発環境

```
1. ngrok で HTTPS トンネルを作成
   $ ngrok http 8000

2. LINE Developersコンソールで Webhook URL を設定
   https://xxxx.ngrok-free.app/webhook

3. FastAPI サーバーを起動
   $ uvicorn main:app --reload --port 8000
```

### ディレクトリ構成（想定）

```
chatbot/
├── main.py              # FastAPI アプリエントリーポイント
├── webhook.py           # Webhook ルーター・イベント処理
├── gemini_client.py     # Gemini API クライアント
├── history_store.py     # 会話履歴の読み書き (Redis/SQLite)
├── config.py            # 環境変数の読み込み
├── requirements.txt     # 依存パッケージ一覧
├── .env.example         # 環境変数テンプレート
├── .gitignore
└── SPEC.md              # 本仕様書
```

---

## 11. 今後の拡張候補

以下は現バージョンのスコープ外だが、将来的に追加を検討する機能。

| 機能 | 説明 |
|------|------|
| マルチモーダル対応 | 画像・PDFを送信してGeminiに質問できる機能 |
| システムプロンプト設定 | botのキャラクター・役割を設定できるコマンド |
| グループチャット対応 | LINEグループ内での応答設定 |
| 利用統計ダッシュボード | メッセージ数・アクティブユーザー数の可視化 |
| レート制限 | ユーザーごとの1日あたり最大メッセージ数の制限 |

---

*本仕様書はプロジェクト進行に合わせて随時更新する。*
