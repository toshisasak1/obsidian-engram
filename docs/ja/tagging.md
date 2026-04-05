# 自動タグ付け

Engram はインデックス済みのエントリに `python`, `docker`, `trading`, `assistant` などの記述的なラベルを自動付与できます。タグを使うことで、特定のトピックやカテゴリに絞った検索が可能になります。

## 概要

タグ付けは同期とは別に実行します。エントリがインデックスされた後にタグ付けを行います:

```bash
engram tag
```

2つのバックエンドが利用可能です:

| バックエンド | 仕組み | コスト | 速度 |
|------------|--------|-------|------|
| `keyword` | ルールベースのパターンマッチング (組み込み + カスタムルール) | 無料 | 即座 |
| `cli` | `claude -p` または `codex -q` にバッチ送信してAIタグ付け | アカウント課金のみ (API従量課金なし) | バッチあたり約10-90秒 |

どちらか単体でも、両方を組み合わせても使えます (`"both"` モードは keyword を先に実行し、その後 CLI で追加タグを付与)。

## 設定

`.engram/config.toml` に `[tagging]` セクションを追加します:

```toml
[tagging]
enabled = true
provider = "keyword"       # "keyword", "cli", "both"
batch_size = 50
max_tags = 5

[tagging.cli]
command = "claude"         # "claude" または "codex"
timeout = 120              # バッチあたりのタイムアウト(秒)

# カスタムキーワードルール (オプション)
[tagging.rules]
python = ["python", "pip", "venv", "pytest"]
trading = ["forex", "gmma", "ema", "bot", "backtest"]
devops = ["docker", "kubernetes", "terraform", "ci/cd"]
```

### 設定項目一覧

| 設定 | デフォルト | 説明 |
|------|----------|------|
| `enabled` | `false` | タグ付け機能を有効化 |
| `provider` | `"keyword"` | 使用するバックエンド: `"keyword"`, `"cli"`, `"both"` |
| `batch_size` | `50` | 1回の実行で処理する最大エントリ数 |
| `max_tags` | `5` | エントリあたりの最大タグ数 |
| `cli.command` | `"claude"` | AIタグ付けに使用するCLIツール: `"claude"` または `"codex"` |
| `cli.timeout` | `120` | CLIバッチ呼び出しのタイムアウト(秒) |
| `rules.*` | (組み込み) | カスタムキーワード→タグのマッピングルール |

## キーワードタガー

キーワードタガーは外部依存なしのパターンマッチングでタグを付与します。

### タグソース (優先順)

1. **ソースアプリ**: エントリを生成したツール (`claude`, `codex`, `gemini`, `vault`)
2. **ロール**: エントリの役割 (`user`, `assistant`, `qa`, `document`)
3. **プロジェクト名**: ソースファイルのパスから抽出 (例: `~/.claude/projects/obsidian-engram/...` → `obsidian-engram`)
4. **カスタムルール**: `[tagging.rules]` で定義したキーワードマッチ (単語境界正規表現)
5. **組み込みルール**: よくある技術キーワード (python, javascript, docker, git, sql 等)

### 組み込みキーワードカテゴリ

| タグ | マッチするキーワード |
|-----|-------------------|
| `python` | python, pip, venv, pytest, django, flask, fastapi |
| `javascript` | javascript, typescript, node, npm, react, vue, angular |
| `rust` | rust, cargo, crate |
| `go` | golang, go mod |
| `sql` | sql, sqlite, postgres, mysql, database, migration |
| `docker` | docker, container, dockerfile, compose |
| `git` | git, commit, branch, merge, rebase, pull request |
| `api` | api, rest, graphql, endpoint, grpc |
| `testing` | test, unittest, pytest, jest, spec, coverage |
| `devops` | deploy, ci/cd, pipeline, kubernetes, terraform |

### カスタムルール

独自のキーワード→タグマッピングを定義できます:

```toml
[tagging.rules]
trading = ["forex", "gmma", "ema", "bot", "backtest"]
ml = ["machine learning", "neural", "model training", "dataset"]
```

キーワードは単語境界マッチ (`\b`) を使用するため、`"python"` は "python" にマッチしますが "pythonic" にはマッチしません。

## CLI タガー

CLI タガーはエントリのテキストを AI ツールに送信し、高精度なタグ付けを行います。既存の Claude Code または Codex CLI のサブスクリプションを使用するため、追加の API 課金はありません。

### 動作の仕組み

1. 未タグのエントリをバッチで収集
2. タグをJSON形式で返すようにプロンプトを構築
3. `claude -p "..."` または `codex -q "..."` をサブプロセスで実行
4. JSONレスポンスをパースしてタグを保存
5. CLI呼び出しが失敗した場合 (タイムアウト、パースエラー)、ログに記録してスキップ

### 前提条件

- **Claude**: `claude` CLI がインストール・認証済みであること (`claude auth login`)
- **Codex**: `codex` CLI がインストール・認証済みであること

CLI タガーは既存のサブスクリプション認証を引き継ぎます。API 従量課金は発生しません。

## CLI コマンド

### 未タグエントリのタグ付け

```bash
# 設定済みのプロバイダーを使用
engram tag

# プロバイダーを上書き指定
engram tag --provider keyword
engram tag --provider cli
engram tag --provider both

# より多くのエントリを処理
engram tag --batch-size 200

# 進捗を表示
engram tag --verbose
```

### タグフィルタ付き検索

```bash
# "python" タグが付いたエントリのみ検索
engram search "エラーハンドリング" --tag python

# 複数タグ (OR マッチ)
engram search "デプロイ" --tag docker,devops
```

### タグ統計の確認

```bash
engram status
```

出力に `Tagged:` 行が含まれ、タグ付け済みエントリ数が表示されます。

## MCP ツール

### `memory_tag`

任意の MCP クライアント (Claude Code, Codex, Gemini/Antigravity) からタグ付けをトリガーできます。

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

**使用例**: AI アシスタントがフィルタ検索の前に `memory_tag` を呼び出して、エントリがタグ付け済みであることを確認できます。

### `memory_search` のタグパラメータ

`memory_search` ツールにオプションの `tags` パラメータが追加されました:

```json
{
  "query": "エラーハンドリング",
  "tags": "python,testing"
}
```

指定したタグのいずれかを持つエントリのみが返されます。

## スケジュール実行

自動タグ付けのために `engram tag` を定期実行できます。

### Windows タスクスケジューラ

付属の `scripts/engram-tag.bat` を使用:

```bat
schtasks /create /tn "Engram Tag Morning" /tr "path\to\engram-tag.bat" /sc daily /st 10:30
schtasks /create /tn "Engram Tag Night"   /tr "path\to\engram-tag.bat" /sc daily /st 00:00
```

### Linux/macOS cron

```cron
30 10 * * * engram tag --provider both --batch-size 200
0  0  * * * engram tag --provider both --batch-size 200
```

バッチスクリプトはキーワードタグ付けを先に実行 (即座)、その後 CLI タグ付け (サブスクリプション使用) を実行します。

## データベーススキーマ

タグは `entry_tags` テーブルに保存されます:

```sql
CREATE TABLE entry_tags (
    entry_id   TEXT NOT NULL REFERENCES entries(entry_id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    method     TEXT NOT NULL DEFAULT 'keyword',  -- 'keyword' または 'cli'
    tagged_at  TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);
```

- タグは小文字に正規化され、重複は除去されます
- エントリを削除すると関連するタグも自動的にカスケード削除されます
- `method` カラムはどのバックエンドがタグを付与したかを記録します
