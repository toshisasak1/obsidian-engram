# 導入ガイド

Obsidian Engramのインストールから初回検索までの手順を解説します。

## 動作要件

- **Python 3.10以上** (3.11以降を推奨)
- **SQLite** (FTS5対応。標準Pythonビルドに含まれます)
- **Obsidian** (オプション。スタンドアロンでも動作可能)

Python のバージョン確認:

```bash
python --version
# Python 3.12.x 以上が表示されればOK
```

## インストール

### 基本インストール (FTS5のみ)

```bash
pip install obsidian-engram
```

FTS5 全文検索のみで動作します。追加のモデルダウンロードは不要です。trigram トークナイザにより日本語も単語分割なしで検索できます。

### ベクトル検索付きインストール

```bash
pip install obsidian-engram[embeddings]
```

`sentence-transformers` と `sqlite-vec` がインストールされ、セマンティック検索(意味的類似性による検索)が使えるようになります。初回実行時に `all-MiniLM-L6-v2` モデル(約80MB)がダウンロードされます。

### OpenAI / Voyage API を使う場合

```bash
pip install obsidian-engram[openai]
```

設定で `provider = "openai"` または `provider = "voyage"` を指定し、APIキーを設定します。詳細は[設定リファレンス](./configuration.md)を参照してください。

### 開発用インストール

```bash
git clone https://github.com/toshisasak1/obsidian-engram.git
cd obsidian-engram
pip install -e ".[dev,embeddings]"
```

## 初期化 (engram init)

### Obsidian Vault 内で使う場合

Vault のルートディレクトリに移動して `engram init` を実行します:

```bash
cd ~/my-vault
engram init
```

`engram init` は以下を自動で行います:

1. `.obsidian/` ディレクトリを検出し、Vault モードで初期化
2. インストール済みの AI ツールを自動検出 (Claude Code, Codex CLI, Gemini CLI)
3. `.engram/config.toml` を生成
4. `.engram/engram.db` (SQLite データベース)を作成
5. アイデンティティテンプレート (`SOUL.md`, `USER.md`, `AGENTS.md`, `TOOLS.md`) を Vault ルートにコピー
6. 検出されたソースの初回同期を実行

実行例:

```
$ cd ~/my-vault
$ engram init

Detected Obsidian vault: /home/you/my-vault
Discovered AI tool sources: claude, codex, gemini

This will:
  - Create .engram/ directory in /home/you/my-vault
  - Initialize database at /home/you/my-vault/.engram/engram.db
  - Copy template files to /home/you/my-vault
  - Run initial sync of 3 source(s)

Proceed? [Y/n]: y

Created /home/you/my-vault/.engram/config.toml
  Created SOUL.md
  Created USER.md
  Created AGENTS.md
  Created TOOLS.md

Initial sync complete: 47 scanned, 32 indexed, 12 skipped, 0 errors

--- MCP Registration ---
Add to your AI tool's MCP config:

  {
    "mcpServers": {
      "engram": {
        "command": "engram",
        "args": ["mcp"],
        "env": {}
      }
    }
  }

Done! Run `engram status` to verify.
```

### スタンドアロンモード (Obsidian なし)

```bash
mkdir ~/engram-memory
cd ~/engram-memory
engram init --no-vault
```

`--no-vault` を指定すると、アイデンティティテンプレートのコピーがスキップされ、`.engram/` ディレクトリのみが作成されます。

### 確認をスキップして実行

```bash
engram init -y
```

`-y` フラグで確認プロンプトをスキップし、デフォルト設定で即座に初期化します。

### 特定の Vault パスを指定

```bash
engram init --vault /path/to/my-vault
```

カレントディレクトリとは別の場所にある Vault を指定できます。

## 初回同期 (engram sync)

`engram init` の実行時に初回同期は自動で行われますが、手動で再同期するには:

```bash
engram sync
```

出力例:

```
Sync complete: 47 scanned, 5 indexed, 42 skipped, 0 errors
```

各カウンタの意味:

| カウンタ | 説明 |
|---------|------|
| **scanned** | 検出されたソースファイルの総数 |
| **indexed** | 新規または変更があり、データベースに書き込まれたファイル数 |
| **skipped** | 変更なし(前回と同じハッシュ)でスキップされたファイル数 |
| **errors** | パースまたは書き込みに失敗したファイル数 |

### 同期の仕組み

Engram はファイルごとに SHA-256 ハッシュを記録し、変更検出を行います。変更のないファイルはスキップされるため、2回目以降の同期は高速です。

ファイルの更新時刻が直近すぎる場合(デフォルト8秒以内)は、エディタの書き込みが完了するのを待つために同期がスキップされます。この値は `config.toml` の `[sync] settle_seconds` で調整できます。

### 特定ソースのみ同期

```bash
engram sync --source claude
```

`--source` オプションで、特定のソースだけを同期できます。Vault ナレッジの同期はスキップされます。

### エンベディングをスキップ

```bash
engram sync --skip-embeddings
```

ベクトル埋め込みの生成をスキップし、テキストのインデックスのみを行います。

## 初回検索 (engram search)

データベースに会話ログが取り込まれたら、検索を試してみましょう:

```bash
engram search "デプロイ戦略"
```

出力例:

```
--- 1. [claude] APIゲートウェイのデプロイ方法を教えて (score: 0.032) ---
...Blue/Greenデプロイを採用し、ロールバックを即座に行えるようにします...

--- 2. [codex] Kubernetes設定の確認 (score: 0.028) ---
...HPA設定とリソースリミットを本番環境に合わせて調整...

--- 3. [vault] インフラ設計メモ (score: 0.019) ---
...CI/CDパイプラインの各ステージを定義...
```

### 検索オプション

```bash
# 結果数を指定
engram search "認証の実装" -n 5

# ソースを絞り込み
engram search "バグ修正" --source claude

# JSON形式で出力
engram search "API設計" --json
```

### JSON出力の例

```bash
engram search "API設計" --json
```

```json
[
  {
    "entry_id": "abc123",
    "session_key": "claude:session-001",
    "source_app": "claude",
    "role": "qa",
    "snippet": "REST APIのエンドポイント設計では...",
    "score": 0.035,
    "timestamp": "2026-04-01T10:30:00+00:00",
    "session_title": "API Gateway設計相談"
  }
]
```

## 日常的な使い方

### 継続的な同期 (watch モード)

```bash
engram watch
```

バックグラウンドでファイルの変更を監視し、自動的に同期します。デフォルトでは30秒間隔でポーリングします。`Ctrl+C` で停止します。

```bash
# ログファイルに出力
engram watch --log /tmp/engram-watch.log
```

### データベース状態の確認

```bash
engram status
```

出力例:

```
Database:   /home/you/my-vault/.engram/engram.db
Vault:      /home/you/my-vault
Schema:     v1
Sessions:   45
Entries:    1234
FTS rows:   1234
Embeddings: 0
Src files:  47
Sources:
  claude: 28 sessions
  codex: 12 sessions
  vault: 5 sessions
```

### コンテキストブリーフの生成

```bash
engram brief
```

現在のワークスペースに関連する最近のセッションとキーワードマッチを Markdown で出力します。AI ツールのコンテキスト注入に便利です。

```bash
# 特定のワークスペースを指定
engram brief --workspace /path/to/project

# 追加のクエリを指定
engram brief -q "認証" -q "API設計"

# JSON形式で出力
engram brief --json

# ファイルに出力
engram brief -o context.md
```

## ディレクトリ構造

初期化後の Vault 構造:

```
your-vault/
  .engram/
    config.toml          # 設定ファイル
    engram.db            # SQLiteデータベース
  SOUL.md                # AIアイデンティティ (テンプレート)
  USER.md                # ユーザープロフィール (テンプレート)
  AGENTS.md              # セッション開始手順 (テンプレート)
  TOOLS.md               # 環境ドキュメント (テンプレート)
```

`.engram/` ディレクトリは `.gitignore` に追加しても問題ありません。アイデンティティファイル (`SOUL.md` 等) はバージョン管理することを推奨します。

## トラブルシューティング

### `engram: command not found`

`pip install` でインストールした実行ファイルへのパスが通っていない可能性があります:

```bash
# パスの確認
python -m engram --version

# pip のインストール先を確認
pip show obsidian-engram

# PATH に追加 (例: ~/.local/bin)
export PATH="$HOME/.local/bin:$PATH"
```

### `No AI tool sources auto-detected.`

AI ツールの会話ログが標準パスに存在しない場合に表示されます。`config.toml` で手動設定できます:

```toml
[sources.claude]
enabled = true
path = "/custom/path/to/claude/projects"
```

自動検出されるパス:
- Claude Code: `~/.claude/projects`
- Codex CLI: `~/.codex`
- Gemini CLI: `~/.gemini/antigravity/brain`

### `FTS5 trigram table unavailable`

Python に FTS5 拡張が含まれていない場合に発生します。ほとんどの標準 Python ビルド (python.org, Homebrew, apt) には含まれていますが、一部のカスタムビルドでは欠けていることがあります。

```bash
# FTS5対応の確認
python -c "import sqlite3; c = sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\")"
```

エラーが出る場合は、Python を再インストールするか、FTS5 対応の SQLite をビルドしてください。

### Windows 環境での注意点

- パスの区切り文字にはフォワードスラッシュ `/` とバックスラッシュ `\` の両方が使えます
- `config.toml` 内のパスはフォワードスラッシュに正規化されます
- WSL2 環境では Windows 側のパスを `/mnt/c/...` 形式で指定します

## 次のステップ

- [設定リファレンス](./configuration.md) -- `config.toml` の全オプション解説
- [自動タグ付け](./tagging.md) -- キーワードルールまたは AI CLI によるタグ付け
- [検索アルゴリズム解説](./search.md) -- ハイブリッド検索の仕組み
- [MCP連携ガイド](./mcp.md) -- AI ツールとの統合方法
- [アイデンティティフレームワーク](./identity.md) -- SOUL.md 等の活用法
