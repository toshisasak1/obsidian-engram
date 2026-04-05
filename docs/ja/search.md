# 検索アルゴリズム解説

Engram のハイブリッド検索は、キーワードマッチング (FTS5) とセマンティック類似性 (ベクトル) を組み合わせ、時間減衰で最新の会話を優先する仕組みです。

## アルゴリズムの全体像

```
クエリ入力
    |
    +---> [Step 1] FTS5 キーワード検索 (BM25 ランキング)
    |         |
    |         v
    |     FTS結果リスト (rank付き)
    |
    +---> [Step 2] ベクトル検索 (コサイン類似度) ※オプション
    |         |
    |         v
    |     ベクトル結果リスト (rank付き)
    |
    +---> [Step 3] Reciprocal Rank Fusion
    |         |
    |         v
    |     統合スコアリスト
    |
    +---> [Step 4] 時間減衰
    |         |
    |         v
    |     最終スコアリスト
    |
    +---> [Step 5] SearchResult オブジェクト生成
              |
              v
          検索結果
```

## Step 1: FTS5 キーワード検索

### FTS5 とは

FTS5 (Full-Text Search 5) は SQLite に組み込まれた全文検索エンジンです。Engram はこれを trigram トークナイザと組み合わせて使用します。

### trigram トークナイザ

通常の全文検索エンジンは単語境界(空白や句読点)でテキストを分割しますが、日本語や中国語にはスペースによる単語区切りがありません。trigram トークナイザは全てのテキストを3文字ずつの連続部分文字列(trigram)に分割してインデックスします。

例えば「デプロイ戦略」は以下の trigram に分割されます:

```
デプロ, プロイ, ロイ戦, イ戦略
```

これにより:
- **言語非依存**: 日本語、中国語、韓国語を特別な辞書なしで処理
- **部分文字列マッチ**: 「戦略」で検索すると「デプロイ戦略」がヒット
- **タイプミス耐性**: 3文字単位なので、部分一致しやすい

### FTS テーブル定義

```sql
CREATE VIRTUAL TABLE entries_fts USING fts5(
    entry_id    UNINDEXED,
    session_key UNINDEXED,
    source_app  UNINDEXED,
    role        UNINDEXED,
    text,
    tokenize = 'trigram',
    content = 'entries',
    content_rowid = 'rowid'
);
```

`text` カラムのみがインデックスされ、他のカラムは `UNINDEXED` (検索対象外だが結果に含まれる) です。`content = 'entries'` は content-sync テーブルを指定しており、`entries` テーブルとの自動同期がトリガーで実現されています。

### クエリのエスケープ

ユーザー入力は FTS5 の特殊文字から安全に処理されます:

1. 特殊文字 (`"`, `'`, `(`, `)`, `*`, `+`, `-`, `:`, `;`, `<`, `>`, `^`, `{`, `}`, `~`) を除去
2. 各トークンをダブルクオートで囲み、リテラルマッチを強制
3. トークン間は暗黙の AND で結合

例: `API "gateway" deploy` は `"API" "gateway" "deploy"` に変換されます。

### BM25 ランキング

FTS5 は BM25 アルゴリズムでランキングを計算します。BM25 は TF-IDF の改良版で、以下を考慮します:

- **Term Frequency (TF)**: ドキュメント内でのクエリ用語の出現頻度
- **Inverse Document Frequency (IDF)**: 全ドキュメント中での用語の希少性
- **ドキュメント長の正規化**: 長いドキュメントのスコアが過度に高くなるのを防止

FTS5 の `rank` カラムは負の BM25 スコア(値が小さいほど関連性が高い)を返します。Engram はこれを順位に変換して RRF に渡します。

### FTS 検索のSQL

```sql
SELECT
    e.entry_id,
    e.session_key,
    e.source_app,
    e.role,
    e.text,
    e.timestamp,
    e.title        AS entry_title,
    e.source_path,
    s.title        AS session_title,
    rank           AS bm25_rank
FROM entries_fts AS f
JOIN entries  AS e ON e.entry_id = f.entry_id
LEFT JOIN sessions AS s ON s.session_key = e.session_key
WHERE entries_fts MATCH ?
ORDER BY rank
LIMIT ?
```

取得件数は `limit * fts_limit_multiplier` で、デフォルトでは要求結果数の5倍の候補を取得します。

---

## Step 2: ベクトル検索 (オプション)

### 概要

ベクトル検索はテキストの「意味」をベクトル空間にマッピングし、コサイン類似度で類似したテキストを見つけます。FTS5 がキーワードの完全一致・部分一致を行うのに対し、ベクトル検索は同義語や言い換えを捕捉できます。

例: 「認証の仕組み」で検索すると、「ログイン処理のフロー」や「auth implementation」もヒットする可能性があります。

### 前提条件

ベクトル検索が使用される条件:
1. `config.toml` の `[embedding] enabled = true`
2. `sqlite-vec` 拡張がロードされている
3. `entry_vec` テーブルが存在する
4. クエリのベクトル化に成功する

いずれかの条件が満たされない場合、ベクトル検索はスキップされ、FTS5 のみの結果が返されます。

### クエリの埋め込み

検索クエリはソースのテキストと同じモデルでベクトル化されます:

- **local**: `sentence-transformers` でローカル実行。初回はモデルの読み込みに時間がかかりますが、2回目以降はキャッシュされます。
- **openai**: OpenAI Embeddings API にリクエスト。
- **voyage**: Voyage AI API にリクエスト (`https://api.voyageai.com/v1`)。

### sqlite-vec によるベクトル検索

```sql
SELECT
    v.entry_id,
    v.distance,
    e.session_key,
    e.source_app,
    e.role,
    e.text,
    e.timestamp,
    e.title        AS entry_title,
    e.source_path,
    s.title        AS session_title
FROM entry_vec AS v
JOIN entries  AS e ON e.entry_id = v.entry_id
LEFT JOIN sessions AS s ON s.session_key = e.session_key
WHERE v.embedding MATCH ?
  AND k = ?
```

`entry_vec` は `vec0` 仮想テーブルで、近傍検索を効率的に実行します。クエリベクトルは `float32` のバイト列として渡されます。

`source_app` フィルタがある場合、sqlite-vec は直接フィルタできないため、多めに取得してから Python 側でフィルタリングします。

---

## Step 3: Reciprocal Rank Fusion (RRF)

### RRF とは

RRF は複数のランキングシステムの結果を統合するための手法です。各システムのスコアではなく「順位」のみを使用するため、スコアのスケールが異なるシステム間でも公平に統合できます。

### 計算式

```
rrf_score(entry) = sum(1 / (K + rank_i))
```

あるエントリが FTS で3位、ベクトルで7位にランクされた場合 (K=60):

```
rrf_score = 1/(60+3) + 1/(60+7)
          = 1/63 + 1/67
          = 0.01587 + 0.01493
          = 0.03080
```

### K パラメータの影響

K は順位間のスコア差を調整します:

**K=10 (小さい値)**:
```
1位: 1/11 = 0.0909
2位: 1/12 = 0.0833
差: 0.0076 (8.4% 減少)
```

**K=60 (デフォルト)**:
```
1位: 1/61 = 0.0164
2位: 1/62 = 0.0161
差: 0.0003 (1.6% 減少)
```

**K=100 (大きい値)**:
```
1位: 1/101 = 0.0099
2位: 1/102 = 0.0098
差: 0.0001 (1.0% 減少)
```

K が大きいほど、FTS とベクトルの結果が「民主的に」ブレンドされます。K が小さいと、各システムの上位結果が強く優遇されます。

### 統合ロジック

1. FTS 結果の各エントリに `1/(K + fts_rank)` を加算
2. ベクトル結果の各エントリに `1/(K + vector_rank)` を加算
3. 両方に出現するエントリはスコアが合算される(ブースト効果)
4. 結果を RRF スコアの降順でソート

FTS とベクトルの両方で高ランクに入るエントリは、片方のみのエントリよりも高いスコアを得ます。これが「ハイブリッド検索」の強みです。

---

## Step 4: 時間減衰 (Time Decay)

### 概要

時間減衰は、最近の会話を優先し、古い会話のスコアを徐々に低下させる仕組みです。放射性物質の半減期と同じ指数減衰モデルを使用します。

### 計算式

```
decay_multiplier = 0.5 ^ (age_days / half_life_days)
final_score = rrf_score * decay_multiplier
```

### 減衰の具体例 (half_life_days = 30)

| 経過日数 | decay_multiplier | 元スコア 0.03 の最終スコア |
|---------|-----------------|-------------------------|
| 0日 (今日) | 1.000 | 0.0300 |
| 7日 (1週間) | 0.851 | 0.0255 |
| 15日 (半月) | 0.707 | 0.0212 |
| 30日 (1ヶ月) | 0.500 | 0.0150 |
| 60日 (2ヶ月) | 0.250 | 0.0075 |
| 90日 (3ヶ月) | 0.125 | 0.0038 |
| 180日 (半年) | 0.016 | 0.0005 |
| 365日 (1年) | 0.010 (下限) | 0.0003 |

### 下限と上限

- **上限**: `1.0` (タイムスタンプが未来の場合)
- **下限**: `0.01` (どんなに古いエントリも完全には消えない)
- **タイムスタンプなし**: `0.5` (中間値)

### 半減期の選択指針

| ユースケース | 推奨 half_life_days |
|------------|-------------------|
| アクティブな開発作業 | 7 -- 14 |
| 日常的な記憶 (デフォルト) | 30 |
| プロジェクトのナレッジベース | 90 -- 180 |
| 永続的なリファレンス | 365+ |

---

## Step 5: SearchResult の構築

最終スコアで再ソートされた結果から、`SearchResult` オブジェクトが構築されます:

```python
@dataclass
class SearchResult:
    entry_id: str            # エントリの一意ID
    session_key: str         # 所属セッションのキー
    source_app: str          # ソース (claude, codex, gemini, vault)
    role: str                # user, assistant, qa, document
    text: str                # 元テキスト全文
    snippet: str             # クエリ一致箇所の前後コンテキスト
    score: float             # 最終スコア (RRF * decay)
    timestamp: str | None    # ISO 8601 タイムスタンプ
    entry_title: str | None  # エントリのタイトル
    session_title: str | None # セッションのタイトル
    source_path: str         # ソースファイルのパス
    fts_rank: int | None     # FTS での順位 (None = FTS にヒットせず)
    vector_rank: int | None  # ベクトルでの順位 (None = ベクトルにヒットせず)
    decay_multiplier: float  # 適用された時間減衰倍率
```

### スニペットの生成

スニペットはクエリのトークンがテキスト中で最初にマッチした位置を中心に、前後150文字を抽出します:

1. クエリをトークンに分割
2. テキスト内で各トークンの出現位置を検索 (大文字小文字を無視)
3. 最も早い位置のマッチを中心に、前後 `context_chars` (デフォルト150) 文字を抽出
4. 先頭が切られた場合は `...` を付加
5. マッチが見つからない場合は、テキストの先頭150文字を返す

---

## グレースフルデグラデーション

Engram は依存関係が不足していても動作するよう設計されています:

| 状態 | 動作 |
|------|------|
| FTS5 が利用不可 | 警告をログに出力し、空の結果を返す |
| ベクトル検索が無効 | FTS5 のみで検索。RRF は FTS 結果のみで計算 |
| sqlite-vec 未ロード | ベクトル検索をスキップ。FTS5 のみ |
| 埋め込みモデル未インストール | ベクトル検索をスキップ。FTS5 のみ |
| タイムスタンプが不正 | `decay_multiplier = 0.5` を適用 |
| クエリが空文字列 | 空の結果リストを返す |

---

## パフォーマンスの考慮事項

### インデックスサイズ

- FTS5 trigram インデックスはテキストの約3-5倍のディスク容量を使用
- ベクトル埋め込み (384次元 float32) はエントリあたり約1.5KB
- 10,000 エントリで FTS + ベクトル合わせて約50-100MB

### 検索速度

- FTS5 検索: 数千エントリで数ミリ秒
- ベクトル検索: sqlite-vec の近傍検索は数十ミリ秒
- RRF 統合と時間減衰: 無視できるほど高速
- 全体: 通常 100ms 以内

### WAL モード

データベースは WAL (Write-Ahead Logging) モードで動作し、読み書きの並行実行をサポートします。MCP サーバーが検索を処理している間に `engram sync` が書き込みを行っても、ブロッキングは最小限です。
