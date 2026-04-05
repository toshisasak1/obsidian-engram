# パーサーリファレンス

Engram はパーサーを通じて各 AI ツールの会話ログと Vault ドキュメントを統一的なデータモデルに変換します。

## データモデル

全てのパーサーは以下の2つのレコードを生成します:

### SessionRecord

```python
@dataclass
class SessionRecord:
    session_key: str      # "source_app:external_id" (一意キー)
    source_app: str       # "claude", "codex", "gemini", "vault"
    source_path: str      # ソースファイルの絶対パス
    external_id: str      # ソース固有のセッション ID
    title: str            # セッションタイトル (最初のユーザーメッセージから生成)
    cwd: str | None       # 作業ディレクトリ
    project: str | None   # プロジェクトパス
    started_at: str | None  # ISO 8601 開始時刻
    updated_at: str | None  # ISO 8601 最終更新時刻
    metadata: dict        # ソース固有のメタデータ
```

### EntryRecord

```python
@dataclass
class EntryRecord:
    entry_id: str         # 全ソース間で一意な ID
    session_key: str      # 所属セッションのキー
    source_app: str       # ソースアプリ名
    source_kind: str      # "message", "qa_chunk", "artifact_chunk", "vault_section"
    source_path: str      # ソースファイルのパス
    ordinal: int          # セッション内の順序番号
    role: str             # "user", "assistant", "qa", "artifact", "document"
    text: str             # テキスト本文
    timestamp: str | None # ISO 8601 タイムスタンプ
    title: str | None     # エントリのタイトル
    metadata: dict        # ソース固有のメタデータ
```

---

## 組み込みパーサー

### Claude Code パーサー (`claude`)

#### ファイル形式

Claude Code は会話を JSONL (1行1JSON) 形式で保存します。

**パス**: `~/.claude/projects/{hash}/{uuid}.jsonl`

各行の JSON 構造:

```json
{
  "type": "human" | "assistant" | "progress" | ...,
  "message": {
    "role": "user" | "assistant",
    "content": "テキスト" | [{"type": "text", "text": "..."}]
  },
  "sessionId": "session-uuid",
  "cwd": "/path/to/project",
  "gitBranch": "main",
  "timestamp": "2026-04-01T10:00:00.000Z",
  "uuid": "entry-uuid"
}
```

#### パース処理

1. JSONL ファイルを1行ずつ読み込み
2. `type` が `progress`, `file-history-snapshot`, `bash_progress` の行はスキップ
3. `message.role` が `user` または `assistant` の行のみ処理
4. `message.content` からテキストを抽出 (文字列またはブロック配列を処理)
5. 連続する (user, assistant) ペアを Q&A チャンクに統合

#### Q&A チャンク統合

Claude パーサーは `build_qa_entries()` を使用して、連続するユーザー質問とアシスタント応答をペアリングします:

```
入力:
  [user] "Pythonでソートする方法は?"
  [assistant] "sorted() 関数を使います..."
  [user] "逆順は?"
  [assistant] "reverse=True を指定します"

出力:
  [qa] "Q: Pythonでソートする方法は?\nA: sorted() 関数を使います..."
  [qa] "Q: 逆順は?\nA: reverse=True を指定します"
```

これにより、質問と回答が一つのインデックスエントリとして検索可能になります。

#### パスの自動検出

- **全プラットフォーム**: `~/.claude/projects`
- `discover_paths()` は `*.jsonl` を再帰検索し、`subagents/` ディレクトリをスキップ

#### セッションタイトル

最初のユーザーメッセージの先頭120文字がタイトルとして使用されます。

#### メタデータ

- `git_branch`: 最初のメッセージの `gitBranch` フィールド
- `cwd`: 作業ディレクトリ

---

### Codex CLI パーサー (`codex`)

#### ファイル形式

Codex CLI は2種類のファイルを生成します:

**1. history.jsonl** (グローバル履歴): `~/.codex/history.jsonl`

```json
{
  "session_id": "session-uuid",
  "ts": 1711929600,
  "text": "ユーザーの入力テキスト"
}
```

**2. セッションファイル**: `~/.codex/sessions/{id}.jsonl`

```json
{"type": "session_meta", "session_id": "...", "cwd": "/path"}
{"type": "event_msg", "role": "user", "text": "...", "ts": 1711929600}
{"type": "response_item", "role": "assistant", "content": [...], "ts": 1711929650}
```

#### パース処理

**history.jsonl の場合**:
1. 行を `session_id` でグループ化
2. 最初のセッショングループのみ処理 (1ファイル = 1セッションの原則)
3. ユーザー入力のみが記録されているため、Q&A ペアリングは行わない
4. Unix タイムスタンプを ISO 8601 に変換

**セッションファイルの場合**:
1. `session_meta` 行からセッション情報を取得
2. `event_msg` と `response_item` からメッセージを抽出
3. `content` フィールドからテキストを抽出 (文字列、`text`, `input_text`, `output_text` ブロックに対応)
4. 連続する (user, assistant) ペアを Q&A チャンクに統合

#### パスの自動検出

- **全プラットフォーム**: `~/.codex`
- `discover_paths()` は `history.jsonl` とセッションディレクトリ内の `*.jsonl` を検出

---

### Gemini CLI パーサー (`gemini`)

#### ファイル形式

Gemini CLI (antigravity) はブレインディレクトリ構造でアーティファクトを保存します:

**パス**: `~/.gemini/antigravity/brain/{uuid}/`

各ブレインディレクトリには以下が含まれます:
- `*.md` -- Markdown アーティファクト
- `*.md.resolved` -- 解決済みバージョン (存在する場合はこちらを優先)
- `*.metadata.json` -- メタデータサイドカー

```json
{
  "title": "アーティファクトタイトル",
  "timestamp": "2026-04-01T10:00:00Z",
  "created_at": "2026-04-01T10:00:00Z"
}
```

#### パース処理

1. ブレインディレクトリを列挙 (`*.md` が1つ以上あるディレクトリ)
2. 各ディレクトリ内の Markdown ファイルを収集
   - `*.md.resolved` が存在する場合、対応する `*.md` はスキップ
   - `*.metadata.json` はコンテンツファイルとして扱わない
3. 各 Markdown ファイルを段落チャンクに分割 (最大4000文字)
4. メタデータサイドカーからタイトルとタイムスタンプを取得

#### 段落チャンク分割

`build_paragraph_entries()` はテキストを空行(`\n\n`)で分割し、4000文字以下のチャンクにバッファリングします:

```
入力テキスト:
  "段落1...\n\n段落2...\n\n段落3(とても長い)..."

出力:
  chunk[0] = "段落1...\n\n段落2..."  (合計 <= 4000文字)
  chunk[1] = "段落3(とても長い)..."   (次のチャンク)
```

#### パスの自動検出

- **全プラットフォーム**: `~/.gemini`
- `discover_paths()` は `antigravity/brain/` 配下の `*.md` を含むディレクトリを列挙

---

### Vault パーサー (`vault`)

#### ファイル形式

Obsidian Vault の `.md` ファイルを処理します。オプションの YAML フロントマターを解析し、`##` 見出しでセクション分割します。

**フロントマターの例**:

```markdown
---
title: プロジェクト計画
tags: [planning, 2026]
created: 2026-03-15
updated: 2026-04-01
---

# プロジェクト計画

## 概要

本プロジェクトは...
```

#### パース処理

1. YAML フロントマター (---で囲まれた部分) を簡易パーサーで解析
   - `key: value` 形式のみ対応
   - インラインリスト `[a, b, c]` に対応
   - ネストされた YAML は非対応 (PyYAML 依存を避けるため)
2. 残りの本文を `##` 見出しでセクションに分割
3. 4000文字を超えるセクションは段落境界でさらに分割
4. 各セクションが1つの `EntryRecord` になる

#### フロントマターの利用

| フロントマターキー | 用途 |
|------------------|------|
| `title` | セッションタイトル (なければファイル名のステム) |
| `tags` | メタデータに格納 (将来のタグフィルタ用) |
| `created` / `date` | セッションの `started_at` |
| `updated` / `modified` | セッションの `updated_at` |

#### 除外ディレクトリ

以下のディレクトリ名は常にスキップされます (ハードコード):

- `.obsidian`
- `.git`
- `.trash`
- `node_modules`
- `__pycache__`

追加の除外パターンは `config.toml` の `[vault_knowledge] exclude` で設定できます。

#### パスの自動検出

Vault パーサーにはデフォルトルートがありません。`config.toml` の `vault_path` から指定されるか、`engram init` 時に検出された Vault パスが使用されます。

---

### VS Code パーサー (`vscode`)

**注意**: VS Code パーサーは現在スタブ実装です。VS Code のチャットエクスポート形式が確定次第、実装される予定です。

```python
class VSCodeParser(BaseParser):
    name = "vscode"

    def discover_paths(self, root: Path) -> Iterable[Path]:
        return []  # 未実装

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        raise NotImplementedError("VS Code parser is not yet implemented")
```

---

## 共通ユーティリティ

全パーサーが共有するベースクラスとユーティリティ関数があります。

### テキスト正規化

`normalize_text()` は全てのテキストに適用されます:

- 連続するスペース/タブを1つのスペースに圧縮
- 3行以上の連続空行を2行に圧縮
- 前後の空白を除去

### テキスト切り詰め

`truncate(text, max_len=200)` はタイトル生成時に使用されます。`max_len` を超える場合は切り詰めて末尾に `...` を付加します。

### Markdown セクション分割

`split_markdown_sections()` は `##` 見出しでテキストを分割します:

- `##` の前のテキストは空文字列の見出しで扱われる
- 4000文字を超えるセクションは段落境界でさらに分割
- 分割されたセクションには `(part 1)`, `(part 2)` が付加される

---

## カスタムパーサーの書き方

### 基本構造

`BaseParser` を継承し、3つのメソッドを実装します:

```python
from collections.abc import Iterable
from pathlib import Path

from engram.models import EntryRecord, SessionRecord
from engram.parsers.base import BaseParser


class MyToolParser(BaseParser):
    """カスタムAIツールのパーサー"""

    name = "my_tool"

    def discover_paths(self, root: Path) -> Iterable[Path]:
        """root 配下のパース対象ファイルを列挙"""
        for p in sorted(root.rglob("*.json")):
            yield p

    def parse(self, path: Path) -> tuple[SessionRecord, list[EntryRecord]]:
        """1ファイルを SessionRecord + EntryRecord リストに変換"""
        import json
        import uuid

        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        session = SessionRecord(
            session_key=f"my_tool:{path.stem}",
            source_app="my_tool",
            source_path=str(path),
            external_id=path.stem,
            title=data.get("title", path.stem),
            started_at=data.get("created_at"),
        )

        entries = []
        for i, msg in enumerate(data.get("messages", [])):
            entries.append(
                EntryRecord(
                    entry_id=str(uuid.uuid4()),
                    session_key=session.session_key,
                    source_app="my_tool",
                    source_kind="message",
                    source_path=str(path),
                    ordinal=i,
                    role=msg.get("role", "user"),
                    text=msg.get("text", ""),
                    timestamp=msg.get("timestamp"),
                    title=None,
                    metadata={},
                )
            )

        return session, entries

    def default_root(self) -> Path | None:
        """デフォルトのルートパス (None の場合は config で指定必須)"""
        return Path.home() / ".my-tool" / "sessions"
```

### entry_points による登録

カスタムパーサーを Python パッケージとして公開し、`entry_points` で登録します。

**pyproject.toml**:

```toml
[project.entry-points."engram.parsers"]
my_tool = "my_package.parser:MyToolParser"
```

**setup.cfg** (旧形式):

```ini
[options.entry_points]
engram.parsers =
    my_tool = my_package.parser:MyToolParser
```

### パーサーの発見ロジック

`get_parser(name)` は以下の順序でパーサーを検索します:

1. 組み込みパーサー (`claude`, `codex`, `gemini`, `vault`, `vscode`)
2. `engram.parsers` グループの entry_points

```python
from engram.parsers import get_parser, list_parsers

# 組み込みパーサー一覧
print(list_parsers())
# ['claude', 'codex', 'gemini', 'vault', 'vscode']

# パーサーの取得
parser = get_parser("claude")
```

### config.toml での使用

```toml
[sources.my_tool]
enabled = true
path = "/path/to/my-tool/data"
parser = "my_tool"  # entry_points で登録した名前
```

### 実装のヒント

1. **discover_paths は軽量に**: ファイルの存在確認のみを行い、内容の読み込みは `parse()` に任せる
2. **parse は冪等に**: 同じファイルを何度パースしても同じ結果を返す
3. **entry_id は一意に**: `uuid.uuid4()` を使うか、ソースファイル固有の ID を使用
4. **session_key の命名規則**: `"source_app:external_id"` 形式を守る
5. **大きなテキストは分割**: 4000文字を目安にチャンクに分割すると、検索精度が向上する
6. **エラーは適切にログ**: `logging.getLogger(__name__)` を使い、スキップした行やファイルを記録
7. **normalize_text を活用**: 空白の正規化で検索品質が向上する

### テストの書き方

```python
from pathlib import Path
from my_package.parser import MyToolParser


def test_parse_basic(tmp_path: Path):
    # テストデータを作成
    data_file = tmp_path / "session.json"
    data_file.write_text('{"title": "test", "messages": [{"role": "user", "text": "hello"}]}')

    parser = MyToolParser()
    session, entries = parser.parse(data_file)

    assert session.source_app == "my_tool"
    assert session.title == "test"
    assert len(entries) == 1
    assert entries[0].text == "hello"


def test_discover(tmp_path: Path):
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.txt").write_text("not json")

    parser = MyToolParser()
    paths = list(parser.discover_paths(tmp_path))

    assert len(paths) == 1
    assert paths[0].name == "a.json"
```
