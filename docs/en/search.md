# Search Algorithm

Engram uses a multi-stage hybrid search pipeline that combines keyword matching and semantic similarity. This document explains how each stage works, why each design decision was made, and how you can tune the parameters.

## Pipeline overview

```
User query
    |
    v
+-------------------+     +---------------------+
| FTS5 keyword      |     | Vector cosine       |
| search (BM25)     |     | similarity search   |
+-------------------+     +---------------------+
    |                           |
    v                           v
+-------------------------------------------+
| Reciprocal Rank Fusion (RRF)              |
| score = sum(1 / (K + rank))               |
+-------------------------------------------+
    |
    v
+-------------------------------------------+
| Time decay                                |
| final = rrf_score * 0.5^(age / half_life) |
+-------------------------------------------+
    |
    v
  Ranked results
```

When vector embeddings are disabled (the default), the pipeline simplifies to FTS5 + time decay. RRF still runs, but with only one input.

## Stage 1: FTS5 keyword search

### How it works

Engram uses SQLite's FTS5 extension with a **trigram tokenizer**. Unlike word-based tokenizers that split text on whitespace, the trigram tokenizer indexes every 3-character sequence in the text.

For example, the text `"deploy"` produces these trigrams: `dep`, `epl`, `plo`, `loy`. A search for `"deploy"` matches any text containing that exact character sequence.

### Why trigrams

Trigram tokenization has two significant advantages:

1. **CJK support**. Japanese, Chinese, and Korean do not use spaces between words. Word-boundary tokenizers fail on these languages. Trigrams work naturally because they index character sequences regardless of word boundaries.

2. **Substring matching**. Searching for `"deploy"` also matches `"redeployment"` and `"auto-deploy"` because the trigram sequences overlap.

The tradeoff is a larger index (more trigrams per document) and slightly higher query cost. In practice, with SQLite and typical vault sizes (tens of thousands of entries), this is not noticeable.

### FTS5 query escaping

User queries are sanitized before being sent to FTS5. The `safe_match_query` function:

1. Strips FTS5 special characters: `" ' ( ) * + - : ; < > ^ { } ~`
2. Splits the cleaned text into whitespace-separated tokens
3. Wraps each token in double quotes for literal matching
4. Joins tokens with implicit AND

For example, the user query `deployment strategy (API)` becomes:

```
"deployment" "strategy" "API"
```

This means all three tokens must appear in a document for it to match.

### BM25 ranking

FTS5 ranks results using BM25, a standard information retrieval scoring function. Results are ordered by BM25 rank (lower is better in SQLite's convention), then assigned a positional rank (1, 2, 3, ...) for the RRF stage.

### Source filtering

When the `source_app` parameter is provided, an additional `WHERE e.source_app = ?` clause restricts FTS results to that source only.

### Candidate limit

The FTS stage fetches `limit * fts_limit_multiplier` candidates (default: `10 * 5 = 50`). This over-fetching ensures that RRF fusion has enough candidates to produce good results after merging and re-ranking.

## Stage 2: Vector cosine similarity search

This stage is only active when:

1. `embedding.enabled = true` in config
2. The `sqlite-vec` extension is loaded and the `entry_vec` table exists
3. The query can be embedded successfully

### How it works

The query text is converted to a vector using the same embedding model used during sync. This vector is compared against all stored entry vectors using cosine distance via `sqlite-vec`'s `MATCH` operator.

The query vector is packed as a raw `float32` blob:

```python
query_blob = struct.pack(f"{len(vec)}f", *vec)
```

And searched with:

```sql
SELECT v.entry_id, v.distance, ...
FROM entry_vec AS v
WHERE v.embedding MATCH ?
  AND k = ?
```

### Source filtering with vectors

The `entry_vec` virtual table does not support arbitrary WHERE clauses directly. When filtering by `source_app`, Engram over-fetches (adds 50 extra candidates) and filters in Python after retrieval.

### Embedding providers

| Provider | How it works |
|----------|-------------|
| `local` | Uses `sentence-transformers` to encode on CPU. The model is cached in memory after first load. |
| `openai` | Calls the OpenAI Embeddings API via the `openai` Python package. |
| `voyage` | Same as `openai` but with the Voyage AI base URL (`https://api.voyageai.com/v1`). |

All vectors are L2-normalized before storage, so cosine similarity reduces to dot product.

### Graceful degradation

If `sentence-transformers` is not installed, or the API key is missing, or `sqlite-vec` is not available, vector search is silently skipped. The pipeline falls back to FTS5-only mode. No error is raised.

## Stage 3: Reciprocal Rank Fusion (RRF)

### The problem RRF solves

FTS5 and vector search produce ranked lists with incompatible scores (BM25 vs. cosine distance). RRF merges them by converting each result's position (rank) into a score, regardless of the original scoring scale.

### The formula

For each unique entry that appears in either result set:

```
rrf_score = sum(1 / (K + rank_i))
```

Where `rank_i` is the position in each result list (1-indexed), and `K` is the RRF constant (`rrf_k` in config, default 60).

**Example**: An entry ranked 1st in FTS and 3rd in vector search with `K=60`:

```
rrf_score = 1/(60+1) + 1/(60+3) = 0.01639 + 0.01587 = 0.03226
```

An entry ranked 2nd in FTS but not in vector results:

```
rrf_score = 1/(60+2) = 0.01613
```

The first entry scores higher because it appeared in both lists.

### The K parameter

`K` controls how much positional rank matters:

- **Low K (10-30)**: The difference between rank 1 and rank 5 is large. Top results dominate.
- **Medium K (50-70)**: The difference is moderate. Results from both methods get reasonable weight.
- **High K (100+)**: The difference is small. Merely appearing in both lists matters more than rank.

The default of 60 is well-studied in information retrieval literature and works well for most use cases.

### Entries in only one list

Entries that appear in only the FTS list or only the vector list still participate. They receive an RRF contribution from just one source. This ensures that strong keyword matches are not lost when vector search does not find them, and vice versa.

## Stage 4: Time decay

### The problem time decay solves

Without time decay, a conversation from two years ago about "deployment" scores the same as one from yesterday. In practice, recent conversations are almost always more relevant because they reflect your current thinking and active projects.

### The formula

```
multiplier = 0.5 ^ (age_days / half_life_days)
final_score = rrf_score * multiplier
```

Where `age_days` is the number of days between the entry's timestamp and now, and `half_life_days` is the configured half-life (default 30).

The multiplier is clamped to `[0.01, 1.0]`:
- An entry from today: `0.5^0 = 1.0` (full score)
- An entry from 30 days ago: `0.5^1 = 0.5` (half score)
- An entry from 60 days ago: `0.5^2 = 0.25` (quarter score)
- An entry from 90 days ago: `0.5^3 = 0.125`
- Very old entries: clamp at `0.01` (never fully disappear)

### Missing timestamps

When an entry has no timestamp (or the timestamp cannot be parsed), the multiplier defaults to `0.5`. This places undated entries in a neutral middle ground -- not prioritized, not buried.

### Timestamp parsing

Engram accepts ISO 8601 timestamps with several variations:
- `2026-04-05T10:30:00Z` (trailing Z)
- `2026-04-05T10:30:00+09:00` (timezone offset)
- `2026-04-05T10:30:00` (naive, assumed UTC)
- `2026-04-05 10:30:00` (space separator)

## Stage 5: Snippet generation

After scoring, Engram builds a text snippet for each result. The `build_snippet` function:

1. Takes the full entry text and the original query
2. Finds the first occurrence of any query token (case-insensitive)
3. Extracts a window of 150 characters on each side of the match
4. Adds `...` ellipsis markers at truncation points
5. Falls back to the first 150 characters if no token is found

The snippet is what you see in CLI output and what MCP tools return to AI clients.

## Practical tuning guide

### "I want more recent results"

Decrease `half_life_days`:

```toml
[search]
half_life_days = 7.0
```

### "Old conversations are still relevant"

Increase `half_life_days`:

```toml
[search]
half_life_days = 180.0
```

### "Search is too slow"

Reduce the limit multipliers:

```toml
[search]
fts_limit_multiplier = 2
vector_limit_multiplier = 2
```

### "FTS results dominate over vector results" (or vice versa)

Adjust `rrf_k`. Lower values give more weight to top-ranked results from each method. Higher values smooth the blending.

### "I want exact keyword matches only"

Disable embeddings:

```toml
[embedding]
enabled = false
```

With FTS5-only search, the trigram tokenizer still provides partial matching (substring matching within tokens), but there is no semantic expansion.

### "I want meaning-based search, keywords are not working"

Enable embeddings:

```toml
[embedding]
enabled = true
provider = "local"
```

Then re-sync: `engram sync`. Vector search captures semantic similarity even when exact keywords differ. For example, searching for "error handling" can match entries about "exception management" or "fault tolerance".

## Database internals

### FTS5 table schema

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

The FTS table is a content-sync table backed by the `entries` table. The `UNINDEXED` columns are stored but not searchable -- they are carried along for convenience in joins. Only the `text` column is indexed.

### Trigger-based sync

Three triggers keep the FTS index consistent:

- `entries_ai` (AFTER INSERT): adds new rows to FTS
- `entries_ad` (AFTER DELETE): removes deleted rows from FTS
- `entries_au` (AFTER UPDATE): removes old, inserts new

This means you never need to manually rebuild the FTS index under normal operation.

### vec0 table schema

```sql
CREATE VIRTUAL TABLE entry_vec USING vec0(
    entry_id TEXT PRIMARY KEY,
    embedding float[384]
);
```

The dimension (`384`) matches the embedding model. The `sqlite-vec` extension provides fast approximate nearest-neighbor search on this table.

### Rebuilding the FTS index

If the FTS index gets corrupted (extremely rare), you can rebuild it:

```python
from engram.db import connect, rebuild_fts
conn = connect(".engram/engram.db")
rebuild_fts(conn)
conn.close()
```

Or simply delete `engram.db` and re-run `engram sync`.
