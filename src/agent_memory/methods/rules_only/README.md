# rules_only

Recall stage, the default when a config has no `[recall]`. Renders the store's active rules only (same `## RULES` format as `tag_recall`) and ignores the route, facts and log. No LLM, no embedder. Rendered rules get `last_used_at = now` via `Store.touch`.

Constants: none.
