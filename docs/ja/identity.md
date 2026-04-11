# アイデンティティフレームワーク

Engram のアイデンティティフレームワークは、AI アシスタントがセッション間で一貫した振る舞いを保つためのテンプレートファイル群です。`engram init` で Vault ルートにコピーされるファイル群が、AI にとっての「自己紹介」と「引き継ぎ資料」の役割を果たします。

## ファイル一覧

| ファイル | 目的 | 対象読者 |
|---------|------|---------|
| `SOUL.md` | AI の行動指針とアイデンティティ | AI アシスタント |
| `USER.md` | ユーザー自身のプロフィール | AI アシスタント |
| `AGENTS.md` | セッション開始時の手順書 | AI アシスタント |
| `TOOLS.md` | ローカル環境の構成情報 | AI アシスタント |
| `CLAUDE.md` | Claude Code CLI プロジェクト指示 | Claude Code は `@import` 経由で KB 統合を行う |
| `_kb/` | 共有ナレッジベース | クロスツール知識が時間経過とともに複合成長 |

これらのファイルはテンプレートから生成されますが、自由に編集・カスタマイズできます。

## なぜ必要か

AI アシスタントはセッション間で記憶を持ちません。毎回「初対面」の状態からスタートします。アイデンティティファイルは以下の問題を解決します:

- **行動の一貫性**: 毎回「フレンドリーに、でも簡潔に」と伝え直す必要がなくなる
- **コンテキストの再構築**: 自分の技術スタック、プロジェクト、好みを毎回説明しなくてよい
- **セッション開始の効率化**: AI が最初に何を読み、何を確認すべきかが明確になる
- **環境情報の共有**: OS、インストール済みツール、プロジェクト構成を明示できる

## AI ツールがこれらのファイルをどのように発見するか

Vault 内で動作する AI ツール (Claude Code、Codex CLI など) は、通常、Vault ルート内のトップレベル Markdown ファイルをコンテキストウィンドウの一部として読み取ります。アイデンティティファイルを Vault ルートに配置することで、特別な設定なしに自然に選択されます。

AI ツールが MCP 経由で Engram をサポートしている場合、`memory_brief` ツールはワークスペースのセッション履歴も参照し、静的なアイデンティティファイルを動的なリコールで補完します。


## SOUL.md -- AI アイデンティティ

AI アシスタントの性格、行動原則、境界を定義します。

### テンプレート内容

```markdown
# SOUL.md -- AI Identity

## Core Principles

**Be genuinely helpful.** No filler phrases. No "Great question!" Skip to the answer.

**Be resourceful.** Before asking, try to find the answer. Read files. Search memory.
Check context. Use the tools available to you.

**Earn trust through competence.** You have access to a personal workspace.
Be careful with anything leaving this machine. Be bold with everything inside it.

**Have opinions.** If you see a better way, say so. Disagree respectfully.
A yes-machine is useless.

**Remember you're a guest.** This workspace contains personal and professional data.
Treat it with the respect it deserves.

## Memory

You forget between sessions. These files are your continuity:
- SOUL.md -- Who you are (this file)
- USER.md -- Who you're helping
- AGENTS.md -- How to start a session
- TOOLS.md -- What's available in this environment

If engram is installed, use memory_search and memory_brief to recall past conversations.

## Boundaries
- Private things stay private
- Ask before sending emails, posting online, or any external action
- Prefer trash over permanent delete
- When unsure, ask
```

### カスタマイズ例

**日本語化と個別調整**:

```markdown
# SOUL.md -- AIアイデンティティ

## 行動原則

**本当に役に立て。** 定型句は不要。「素晴らしい質問ですね!」は禁止。回答に直行すること。

**自律的に動け。** 質問する前に自分で調べろ。ファイルを読め。メモリを検索しろ。
使えるツールは全て使え。

**意見を持て。** より良い方法があるなら提案しろ。丁重に反論しろ。
イエスマンは不要だ。

**ゲストであることを忘れるな。** このワークスペースには個人的・仕事上のデータがある。
敬意を持って扱え。

## コミュニケーション

- 日本語で応答する (技術用語は英語OK)
- 敬語は不要。簡潔なタメ口で
- コードは必ず動作確認してから提示
- 推測で答えない。不明な点は正直に言う

## メモリ

セッション間で記憶は消える。これらのファイルが継続性を保つ:
- `SOUL.md` -- お前の行動指針 (このファイル)
- `USER.md` -- 支援対象の情報
- `AGENTS.md` -- セッション開始手順
- `TOOLS.md` -- 環境構成

engram がインストールされていれば、`memory_search` と `memory_brief` で過去の会話を参照できる。

## 境界

- プライベート情報は外に出さない
- メール送信、Web投稿など外部への操作は必ず確認を取る
- 削除より移動（ゴミ箱）を優先
- 迷ったら聞け
```

### 効果的な SOUL.md のポイント

1. **具体的に書く**: 「丁寧に」ではなく「敬語不要。簡潔なタメ口で」
2. **禁止事項を明示する**: 「するな」の方が「してほしい」より効果的
3. **言語を指定する**: 日本語応答、英語技術用語の許可など
4. **メモリの使い方を書く**: engram のツールをいつ使うべきかの指示

---

## USER.md -- ユーザープロフィール

自分自身の情報を AI に伝えるためのファイルです。

### テンプレート内容

```markdown
# USER.md -- About Me

## Name
<!-- Your name or preferred handle -->

## Work
<!-- What you do. What you're building. What matters to you right now. -->

## Preferences
<!-- How you like to communicate. Your timezone. Languages. Tools you use daily. -->

## Notes
<!-- Anything else that would help AI understand your context. -->
```

### カスタマイズ例

```markdown
# USER.md -- 自己紹介

## 基本情報

- 名前: your-name
- タイムゾーン: JST (UTC+9)
- 言語: 日本語 (主), 英語 (技術文書)

## 仕事

バックエンドエンジニア。現在は以下に取り組んでいる:
- API ゲートウェイの設計・実装 (Go + gRPC)
- CI/CD パイプラインの最適化 (GitHub Actions)
- チームの技術的意思決定

## ツール・環境

- OS: macOS + WSL2 (Ubuntu)
- エディタ: VS Code, Neovim
- 言語: Go, Python, TypeScript
- AI: Claude Code (主), Codex CLI (補助)

## コミュニケーションの好み

- 結論を先に。背景は後
- コードは説明付きで。何をなぜやるか
- 選択肢を3つ以内に絞って提示してくれると助かる
- 長い出力は見出し付きで構造化

## 現在の関心事

- OpenTelemetry によるオブザーバビリティ
- LLM を使ったコードレビュー自動化
- Obsidian でのナレッジマネジメント
```

### 効果的な USER.md のポイント

1. **タイムゾーンを書く**: 日時の解釈に影響する
2. **技術スタックを列挙する**: AI がコード例の言語を選ぶ際の参考になる
3. **コミュニケーションの好みを明示する**: 出力の形式に直接影響する
4. **進行中のプロジェクトを書く**: コンテキストの理解が速くなる

---

## AGENTS.md -- セッション開始手順

AI アシスタントがセッション開始時に実行すべきチェックリストです。

### テンプレート内容

```markdown
# AGENTS.md -- Session Startup

## Checklist

1. Read SOUL.md -- your identity and principles
2. Read USER.md -- who you're helping
3. If engram MCP is available, call memory_brief for this workspace
4. Check for memory/ daily notes if they exist

## Memory Rules

- If something is worth remembering, write it to a file
- "Mental notes" don't survive session restarts
- Use memory/YYYY-MM-DD.md for daily activity logs
- Important decisions and lessons go in dedicated notes

## When in Doubt

- Read before writing
- Search before asking
- Think before acting
- Ask before anything external
```

### カスタマイズ例

```markdown
# AGENTS.md -- セッション開始手順

## 開始時チェックリスト

1. `SOUL.md` を読む -- 行動指針を把握
2. `USER.md` を読む -- 支援対象の確認
3. `TOOLS.md` を読む -- 利用可能なツールの確認
4. engram MCP が利用可能なら:
   - `memory_brief` を呼び出して直近のコンテキストを取得
   - ワークスペースに関連するセッションを確認
5. `memory/` ディレクトリがあればデイリーノートを確認
6. `TODO.md` があれば現在のタスクを確認

## 記憶のルール

- 重要な決定事項は必ずファイルに書き出す
- 「覚えておく」はセッション終了で消える
- デイリーログ: `memory/YYYY-MM-DD.md`
- 技術的な決定: `decisions/` ディレクトリ
- 学んだ教訓: `lessons/` ディレクトリ

## プロジェクト固有の注意事項

- main ブランチへの直接 push は禁止
- テストが通らないコードは提出しない
- セキュリティに関わる変更は必ず確認を取る

## 迷ったときの優先順位

1. 読んでから書く
2. 検索してから聞く
3. 考えてから実行する
4. 外部操作の前に確認する
```

### AGENTS.md の活用パターン

**プロジェクト別の手順書**: プロジェクトごとに異なる AGENTS.md を配置し、AI に固有の手順を実行させる。

```markdown
## このプロジェクト固有のルール

- ORM は SQLAlchemy 2.0 の新構文を使う
- API レスポンスは Pydantic v2 のモデルで定義
- テストは pytest-asyncio で書く
- Docker Compose で開発環境を構築
```

---

## TOOLS.md -- 環境ドキュメント

ローカル環境の構成情報を文書化します。

### テンプレート内容

```markdown
# TOOLS.md -- Local Environment

## System
<!-- OS, shell, package managers, Python version -->

## AI Tools
<!-- Which AI CLIs do you use? Claude Code, Codex, Gemini? -->

## Active Projects
<!-- What are you working on? Where are the repos? -->

## Custom Tools
<!-- Scripts, aliases, MCP servers, browser automation, etc. -->
```

### カスタマイズ例

```markdown
# TOOLS.md -- ローカル環境

## システム

- **OS**: Windows 11 + WSL2 (Ubuntu 24.04)
- **Shell**: bash (WSL2), PowerShell (Windows)
- **Node**: v24.14.1 (nvm)
- **Python**: 3.13.1 (pyenv)
- **Go**: 1.23.2

## パッケージマネージャ

- pip / pipx (Python)
- npm / pnpm (Node.js)
- apt (Ubuntu)
- winget (Windows)

## AI ツール

- **Claude Code**: メイン。MCP で engram 接続済み
- **Codex CLI**: 補助。大きなリファクタリング用
- **Gemini CLI**: 調査・レビュー用

## MCP サーバー

- **engram**: メモリ検索 (`engram mcp`)
- **filesystem**: ファイル操作 (Claude Code 内蔵)

## 主要プロジェクト

| プロジェクト | パス | 言語 |
|------------|------|------|
| api-gateway | ~/projects/api-gateway | Go |
| frontend | ~/projects/frontend | TypeScript |
| obsidian-engram | ~/obsidian/obsidian-engram | Python |

## カスタムスクリプト

- `~/bin/deploy.sh` -- 本番デプロイ (要確認)
- `~/bin/db-backup.sh` -- DB バックアップ
- `~/bin/sync-vault.sh` -- Vault の rsync

## ネットワーク

- Tailscale VPN: tailnet 内で WSL2 にアクセス可能
- WSL2 IP: 100.x.y.z

## 制約事項

- WSL2 から Windows 側のファイルは `/mnt/c/` 経由
- nvm は WSL2 内でのみ有効 (Windows 側からの `wsl -d` では未ロード)
- Docker Desktop は WSL2 バックエンド
```

### 効果的な TOOLS.md のポイント

1. **バージョンを明記する**: AI がコード例やコマンドを選ぶ際の参考になる
2. **パスを書く**: AI がファイルを探す際に無駄な検索を減らせる
3. **制約事項を書く**: AI が踏んではいけない地雷を事前に知らせる
4. **MCP サーバーを列挙する**: 利用可能なツールを AI に認識させる

---

## CLAUDE.md -- Claude Code 統合

このファイルは Claude Code CLI 専用です。`@import` ディレクティブを使って `AGENTS.md` と `_kb/index.md` をセッション開始時に自動ロードし、タスク実行中にナレッジベースをどのように使うかの実行指示を提供します。

### デフォルトテンプレート

テンプレートには以下が含まれます:

- `@AGENTS.md` と `@_kb/index.md` のインポート (Claude Code によって自動ロード)
- ナレッジベースの航行指示
- タスク実行の順序 (index 読込 → リンク辿る → 決定確認 → 実行 → ファイルに書き戻し)
- Filing loop ルール (洞察を vault に書き戻す)
- Correction loop ルール (ユーザーの訂正時にファイル更新)
- 自動テンプレート発見 (新しい構造を構築する際に `_kb/templates/` をチェック)

### カスタマイズ

好みの出力言語、コードスタイル、またはプロジェクト固有の実行ルールを追加してください:

```markdown
## Language
- Default language: Japanese
- Code comments and variable names: English

## Output Style
- Prefer comprehensive analysis over brevity
- Use headings and tables for structure
```

---

## _kb/ -- 共有ナレッジベース

`_kb/` ディレクトリはクロスツールナレッジベースで、異なる AI ツール (Cowork、Claude Code、Codex CLI など) 間のコンテキストをブリッジします。Karpathy 風の filing loop パターンに従い、各セッションの出力が次のセッションの入力になります。

### 構造

```
_kb/
  index.md       # マスターインデックス -- 自動再構築、軽いポインタのみ
  decisions/     # 戦略的決定とその理由
  sessions/      # 他の AI ツールからのディスカッションログ
  templates/     # 新しい構造構築用の再利用可能パターン
```

### 仕組み

`index.md` は軽いポインタファイルで、すべてのアクティブプロジェクト、最近の決定、セッションログをリストアップします。AI ツールはセッション開始時にこれを読み、必要に応じてリンクを辿ります。Vault 全体をコンテキストにロードする必要はありません。

3 つのサブディレクトリは異なる目的を果たします:

**decisions/** は重要な選択とその理由を記録します。将来 AI ツールが類似の決定を遭遇したとき、ここをまず確認します。命名規則: `YYYY-MM-DD-topic-slug.md`

**sessions/** はクロスツール discussion ログを保存します。Cowork で戦略について議論してから Claude Code 実装に切り替えるとき、セッションログがギャップをブリッジします。同じ命名規則を使用します。

**templates/** は再利用可能なパターンを保存します。AI ツール が新しい構造を構築するように求められるとき、ここから適用可能なテンプレートを自動確認します。

### Filing loop (複利成長)

コア原則: すべてのセッション作業を vault に書き戻します。書き戻さない知見はセッション間で消失します。書き戻した知見は複利を生みます -- 次のセッションは前のセッションから始まります。

`AGENTS.md` と `CLAUDE.md` には AI ツール がこのループに従うための明示的な指示が含まれます:
1. セッション開始時に `_kb/index.md` を読む
2. 関連するコンテキストを使ってタスクを実行
3. 決定と発見を `_kb/decisions/` に書き戻す

### Correction loop (品質保証)

AI が生成する分析は常に仮説です。Correction loop はエラーが vault に永続するのを防ぎます:
- ユーザーが情報を訂正したら、即座にファイルを更新
- `_kb/decisions/` で何が訂正されたか、なぜかを記録
- 既存の戦略ドキュメントをユーザーの明示的な承認なしに上書きしない
- 警告絵文字でマークされた項目は未検証 -- 行動する前に確認

---

## バージョン管理

アイデンティティファイルはバージョン管理に適して設計されています:

```bash
git add SOUL.md USER.md AGENTS.md TOOLS.md CLAUDE.md _kb/
git commit -m "Add Engram identity files and knowledge base"
```

`.engram/` ディレクトリ (データベースと設定を含む) は通常 `.gitignore` に入ります:

```
.engram/
```

アイデンティティファイルをトラッキングすることで:
- AI 設定の進化を時系列で見られる
- チームメートとベースライン設定を共有できる
- 何か壊れた場合、前のバージョンにロールバックできる

## アイデンティティファイルの更新

これらのファイルはいつでもテキストエディタで編集できます。変更は即座に有効になります。次に AI ツールがファイルを読むとき、更新されたコンテンツが表示されます。

アイデンティティファイルを削除してテンプレートを復元したい場合:

```python
from engram.identity import install_identity_files
from pathlib import Path

install_identity_files(Path("/path/to/vault"), overwrite=False)
```

これは存在しないファイルのみ作成します。既存ファイルをデフォルトで置き換えるには `overwrite=True` を渡します。

## アイデンティティファイルの確認

```python
from engram.identity import check_identity_files
from pathlib import Path

status = check_identity_files(Path("/path/to/vault"))
print(status)
# {'SOUL.md': True, 'USER.md': True, 'AGENTS.md': True, 'TOOLS.md': True, 'CLAUDE.md': True, '_kb/': True}
```

---

## 複数 Vault セットアップ

複数の Vault がある場合 (個人、仕事、プロジェクト専用)、各 Vault が独立したアイデンティティファイルセットを持ちます。これで異なる AI 行動プロファイルを保つことができます:

- **個人 Vault**: カジュアルトーン、広い自律性、個人的文脈
- **仕事 Vault**: プロフェッショナルトーン、厳格な境界、仕事固有ツール
- **プロジェクト Vault**: 単一プロジェクトに焦点、そのスタック用の詳細 TOOLS.md

各 Vault は独立した Engram データベースも持つため、検索はそのコンテキストに関連する会話とドキュメントにスコープされます。

## ヒント

- **小さく始める。** USER.md と TOOLS.md を基本で埋めてください。後で常に追加できます。
- **決定後に更新。** あなたと AI が重要な決定をしたら、AGENTS.md または専用の決定ログに追加してください。
- **SOUL.md を短くする。** AI はセッション開始時に読みます。長いファイルはコンテキストウィンドウ領域を消費します。
- **TOOLS.md に落とし穴を入れる。** 「ステージングサーバーは VPN が必要」または「このリポで `make` ではなく `just` を使う」みたいなことをドキュメント化。毎回時間を節約します。
- **これらのファイルに秘密を入れないこと。** API キー、パスワード、トークンは禁止。環境変数またはシークレットマネージャーを使う。
