# MCP 連携ガイド

MCP (Model Context Protocol) は AI ツールがローカルのサービスと通信するための標準プロトコルです。Engram は MCP サーバーとして動作し、AI ツールが会話中に過去のメモリを参照できるようにします。

## MCP サーバーの概要

- **プロトコル**: MCP 2024-11-05 (JSON-RPC 2.0 / Content-Length フレーミング)
- **トランスポート**: stdio (標準入出力)
- **ツール数**: 5つ
- **認証**: なし (ローカル実行のみ)
- **ログ**: stderr に出力 (stdout は MCP 通信専用)

## 設定方法

### Claude Code

`.claude/settings.json` またはグローバル MCP 設定に追加します:

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {}
    }
  }
```

**プロジェクト固有の設定** (`.claude/settings.local.json`):

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {
        "ENGRAM_VAULT_PATH": "/path/to/my-vault"
      }
    }
  }
}
```

### Codex CLI

Codex CLI の MCP 設定ファイルに追加します:

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"]
    }
  }
}
```

### Vault パスの指定

MCP サーバーは起動時にカレントディレクトリから Vault を検出しますが、環境変数で明示的に指定することもできます:

```json
{
  "mcpServers": {
    "engram": {
      "command": "engram",
      "args": ["mcp"],
      "env": {
        "ENGRAM_VAULT_PATH": "/home/you/my-vault"
      }
    }
  }
}
```

### Python の仮想環境を使っている場合

仮想環境にインストールした場合は、`engram` コマンドのフルパスを指定します:

```json
{
  "mcpServers": {
    "engram": {
      "command": "/home/you/.venvs/engram/bin/engram",
      "args": ["mcp"]
    }
  }
}
```

Windows の場合:

```json
{
  "mcpServers": {
    "engram": {
      "command": "C:\\Users\\you\\.venvs\\engram\\Scripts\\engram.exe",
      "args": ["mcp"]
    }
  }
}
```

### pipx でインストールした場合

`pipx` でインストールした場合は、pipx のパスを使用します:

```bash
# engram のパスを確認
which engram
# /home/you/.local/bin/engram
```

```json
{
  "mcpServers": {
    "engram": {
      "command": "/home/you/.local/bin/engram",
      "args": ["mcp"]
    }
  }
}
```

---

## MCPツール詳細

### `memory_search`

過去の全会話履歴と Vault ドキュメントを横断検索します。

**入力スキーマ**:

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "検索クエリ (キーワードまたは自然言語)"
    },
    "limit": {
      "type": "integer",
      "description": "最大結果数",
      "default": 10
    },
    "source_app": {
      "type": "string",
      "description": "ソースフィルタ: claude, codex, gemini, vault"
    },
    "tags": {
      "type": "string",
      "description": "カンマ区切りのタグフィルタ (例: 'python,trading')"
    }
  },
  "required": ["query"]
}
```

**使用例**:

AI ツールが自動的に呼び出す場合:

```
ユーザー: 「先週話した API 認証の方法を思い出して」
AI: (memory_search を呼び出し)
     query: "API 認証"
     limit: 5
```

**出力フォーマット**:

```markdown
### 1. [claude] APIゲートウェイ認証の実装
- Score: 0.032
- Time: 2026-04-01T10:30:00+00:00
- Session: claude:session-abc123

...OAuth 2.0のPKCEフローを使用して認証を実装します。
フロントエンドからのリクエストには...

### 2. [codex] JWT実装の確認
- Score: 0.028
- Time: 2026-03-28T15:00:00+00:00
- Session: codex:session-def456

...JWTトークンの検証ミドルウェアを追加し、
有効期限チェックを組み込む必要があります...
```

**ヒント**:
- `source_app` を指定して特定ツールの会話に絞り込める
- 日本語クエリと英語クエリの両方が検索可能 (trigram トークナイザ)
- ベクトル検索が有効な場合、意味的に類似した結果も返される

---

### `memory_brief`

現在のワークスペースに関連する最近のセッションとキーワードマッチをまとめたコンテキストブリーフを生成します。

**入力スキーマ**:

```json
{
  "type": "object",
  "properties": {
    "workspace": {
      "type": "string",
      "description": "ワークスペースパス (デフォルト: カレントディレクトリ)"
    },
    "queries": {
      "type": "array",
      "items": {"type": "string"},
      "description": "追加の検索キーワード"
    }
  }
}
```

**使用例**:

```
ユーザー: 「このプロジェクトの経緯を教えて」
AI: (memory_brief を呼び出し)
     workspace: "/home/you/projects/api-gateway"
```

**出力フォーマット**:

```markdown
# Session Memory Brief

Generated: 2026-04-05T10:00:00+00:00
Workspace: /home/you/projects/api-gateway

## Recent Sessions

### [claude] APIゲートウェイ認証の実装
- Session: claude:session-abc123
- Updated: 2026-04-04T15:00:00+00:00
- CWD: /home/you/projects/api-gateway

> OAuth 2.0のPKCEフローを使用して認証を実装。
> フロントエンドのリクエスト処理を修正。

### [codex] エンドポイントのテスト追加
- Session: codex:session-def456
- Updated: 2026-04-03T09:00:00+00:00
- CWD: /home/you/projects/api-gateway

> pytest-asyncioを使用した非同期テストの追加。

## Keyword Matches

**api-gateway**:
- [claude] claude:session-abc123: APIゲートウェイの設計... (score: -2.500)
```

**ワークスペースマッチングの仕組み**:

1. ワークスペースパスから意味のあるコンポーネント (プロジェクト名など) を抽出
2. セッションの `cwd`, `project`, `source_path` とパス包含チェック
3. セッションの `title`, `project`, `source_path` とキーワードマッチ
4. マッチしたセッションの最新N件を返す
5. ワークスペースのキーワードと追加クエリで FTS 検索

---

### `memory_tag`

データベース内の未タグエントリにタグを付与します。キーワードルールおよび/またはAI CLIツールを使用します。

**入力スキーマ**:

```json
{
  "type": "object",
  "properties": {
    "provider": {
      "type": "string",
      "enum": ["keyword", "cli", "both"],
      "description": "タグ付け方法 (デフォルト: 設定値)"
    },
    "batch_size": {
      "type": "integer",
      "description": "処理する最大エントリ数",
      "default": 50
    }
  }
}
```

**出力**: タグ付け実行の結果サマリー (処理数、タグ付け数、スキップ数、エラー数)

**使用シーン**:
- フィルタ検索 (`memory_search` の `tags` パラメータ) の前にエントリがタグ付け済みであることを確認
- 定期的なメンテナンス操作として実行

---

### `memory_status`

データベースの統計情報を JSON で返します。

**入力スキーマ**:

```json
{
  "type": "object",
  "properties": {}
}
```

**出力例**:

```json
{
  "sessions": 45,
  "entries": 1234,
  "source_files": 47,
  "fts_rows": 1234,
  "embeddings": 0,
  "schema_version": 1,
  "sources": {
    "claude": 28,
    "codex": 12,
    "vault": 5
  },
  "db_path": "/home/you/my-vault/.engram/engram.db",
  "vault_path": "/home/you/my-vault"
}
```

**使用シーン**:
- メモリの状態確認
- 同期が正しく行われているかの検証
- デバッグ時のデータベース容量確認

---

### `memory_list_sessions`

最近の会話セッションをタイトルとタイムスタンプ付きでリスト表示します。

**入力スキーマ**:

```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "default": 20,
      "description": "最大セッション数"
    },
    "source_app": {
      "type": "string",
      "description": "ソースフィルタ"
    }
  }
}
```

**出力例**:

```markdown
- **[claude]** APIゲートウェイ認証の実装
  - Updated: 2026-04-04T15:00:00+00:00
  - CWD: /home/you/projects/api-gateway
  - Key: claude:session-abc123
- **[codex]** データベースマイグレーション
  - Updated: 2026-04-03T09:00:00+00:00
  - CWD: /home/you/projects/backend
  - Key: codex:session-def456
- **[vault]** インフラ設計メモ
  - Updated: 2026-04-02T12:00:00+00:00
  - Key: vault:/home/you/my-vault/infra-design.md
```

**使用シーン**:
- どんな会話をしたかの概観
- 特定セッションの session_key を確認してから `memory_search` で詳細検索

---

## AI ツールからの活用パターン

### パターン 1: セッション開始時のコンテキスト注入

AI ツールが新しいセッションを開始する際に `memory_brief` を呼び出し、過去の文脈を自動的に取得します。

```
[セッション開始]
AI: (memory_brief を呼び出し、workspace = CWD)
AI: 「前回のセッションで API 認証の実装を進めていましたね。
     OAuth 2.0 の PKCE フローまで完了していて、
     次はリフレッシュトークンの処理を実装する予定でした。」
```

### パターン 2: 過去の決定事項の参照

ユーザーが過去に議論した内容について質問した際に `memory_search` を使用します。

```
ユーザー: 「DBのインデックス戦略はどう決めたっけ?」
AI: (memory_search を呼び出し、query = "データベース インデックス 戦略")
AI: 「3月28日の Codex セッションで議論しました。
     複合インデックスを (user_id, created_at) の順序で作成し、
     カバリングインデックスにすることで全カラムの取得を回避する方針でした。」
```

### パターン 3: 横断的な知識の活用

異なるツール間の会話を統合して回答します。

```
ユーザー: 「デプロイ周りの全体像をまとめて」
AI: (memory_search を呼び出し、query = "デプロイ CI/CD")
AI: 「複数のセッションから情報を集約しました:
     - Claude での議論: Blue/Green デプロイ戦略
     - Codex での作業: GitHub Actions のワークフロー設定
     - Vault のメモ: 本番環境のインフラ構成図
     これらを統合すると...」
```

### パターン 4: AGENTS.md との連携

`AGENTS.md` に `memory_brief` の呼び出しを記述しておくと、AI ツールがセッション開始時に自動的に実行します:

```markdown
# AGENTS.md

## セッション開始チェックリスト

1. SOUL.md を読む
2. USER.md を読む
3. **engram MCP が利用可能なら `memory_brief` を呼び出す**
4. memory/ ディレクトリのデイリーノートを確認
```

---

## MCP サーバーの手動起動とテスト

### サーバーの直接起動

```bash
engram mcp
```

サーバーは stdin からの JSON-RPC メッセージを待ち受けます。stderr にログが出力されます。`Ctrl+C` で停止します。

### 手動テスト (JSON-RPC)

テスト用にパイプで JSON-RPC メッセージを送信できます:

```bash
# initialize リクエスト
printf 'Content-Length: 73\r\n\r\n{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}' | engram mcp 2>/dev/null
```

期待される応答:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "engram", "version": "0.1.0"},
    "capabilities": {"tools": {}}
  }
}
```

### ツール一覧の確認

```bash
printf 'Content-Length: 73\r\n\r\n{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}\r\nContent-Length: 52\r\n\r\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | engram mcp 2>/dev/null
```

---

## トラブルシューティング

### MCP サーバーが起動しない

**症状**: AI ツールのログに接続エラーが表示される

**確認事項**:
1. `engram` コマンドが PATH に通っているか
   ```bash
   which engram
   engram --version
   ```
2. データベースが初期化されているか
   ```bash
   engram status
   ```
3. Python の仮想環境が正しいか (フルパスで指定する)

### 検索結果が返らない

**症状**: `memory_search` が "No results found." を返す

**確認事項**:
1. 同期が実行されているか
   ```bash
   engram status
   # Entries: 0 なら同期が必要
   engram sync
   ```
2. ソースが正しく設定されているか
   ```bash
   engram status --json | python -m json.tool
   ```
3. FTS5 が利用可能か (ログに警告が出ていないか)

### MCP ツールがAIツールに表示されない

**症状**: AI ツールのツールリストに engram のツールが出ない

**確認事項**:
1. MCP 設定の JSON 構文が正しいか (カンマの過不足に注意)
2. AI ツールを再起動したか
3. `engram mcp` を手動実行してエラーが出ないか

### stderr にエラーが出る

MCP サーバーは全てのログを stderr に出力します。AI ツール経由で起動した場合、AI ツールのログディレクトリで確認できます。

手動でデバッグする場合:

```bash
engram mcp 2>engram-mcp.log
# 別のターミナルでログを監視
tail -f engram-mcp.log
```

### Windows 特有の問題

- **パスの区切り文字**: MCP 設定の JSON 内ではバックスラッシュ `\` をエスケープ (`\\`) するか、フォワードスラッシュ `/` を使用
- **改行コード**: Content-Length フレーミングは `\r\n` を使用 (プロトコル仕様)
- **文字コード**: UTF-8 で処理されます。日本語を含むクエリも正常に動作します

---

## アーキテクチャ

### プロセスモデル

```
AI ツール (Claude Code / Codex)
    |
    | stdio (stdin/stdout)
    | Content-Length: N\r\n\r\n{JSON-RPC}
    |
    v
engram mcp プロセス
    |
    | SQLite (WAL mode)
    |
    v
.engram/engram.db
```

MCP サーバーは AI ツールの子プロセスとして起動されます。stdin から JSON-RPC リクエストを受け取り、stdout に JSON-RPC レスポンスを返します。全てのログは stderr に出力されるため、stdout の MCP 通信チャネルが汚染されることはありません。

### リクエスト/レスポンスの流れ

1. AI ツールが `tools/call` リクエストを送信
2. MCP サーバーがツール名に基づいてハンドラーにディスパッチ
3. ハンドラーが SQLite データベースに対してクエリを実行
4. 結果を `content` 配列にフォーマットして返却
5. エラーが発生した場合は `isError: true` と共にエラーメッセージを返却

### 対応するライフサイクルメソッド

| メソッド | 処理 |
|---------|------|
| `initialize` | サーバー情報とケイパビリティを返す |
| `notifications/initialized` | 無視 (通知) |
| `ping` | 空のレスポンスを返す |
| `tools/list` | 5つのツール定義を返す |
| `tools/call` | ツールを実行して結果を返す |
