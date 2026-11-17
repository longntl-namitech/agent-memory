# scored_recall

Recall stage. `ScoredRecall(embedder=None).recall(task, store, now, route) -> str`. Ranks the entries the route returned (it does not re-select from the store) in the style of Generative Agents:

```
score = recency + importance + relevance          (equal weights, each in about [0, 1])
recency    = DECAY ** hours_since_last_used       (simulated hours, from entry.last_used_at to now, never below 0)
importance = entry.importance / 10
relevance  = cosine(embed(query), embed(entry.text))
```

The query is the string values of `task.lead` plus the task tags. Facts and log lines are ranked together and the top `TOP_K` are kept. Rules are the always-loaded part: every rule the route returned is kept and is not counted against `TOP_K`. Output uses the shared `render` from `tag_recall` (rules plain, `key: text` facts, log plain). Every rendered entry is marked used via `Store.touch(ids, now)`.

Constants:

- `DECAY = 0.995` per simulated hour. Half-life is about 138 hours (roughly 6 days): an entry unused for a simulated week keeps about 43% of its recency, so recency separates this week's entries from months-old ones without wiping out an old but important or relevant entry.
- `TOP_K = 8` (facts and log lines, rules excluded).
- Weights: 1, 1, 1.

Embedder: pass one in (tests do), or leave `None` for the registry's no-argument build. Then it is created lazily on first use: `OpenAICompatEmbedder` (disk-cached by `core/embed.py`, cache dir `EMBEDDING_CACHE_DIR`, default `.cache/embeddings`) when `EMBEDDING_BASE_URL` and `EMBEDDING_MODEL` are set, else the offline `FastembedEmbedder`. Entry texts not yet embedded in this instance go in one batched call per recall.

Works on both the simulation and LongMemEval; it is the recall for LongMemEval configs, where there are no tags for `tag_recall` to use. Time comes only from `now`.
