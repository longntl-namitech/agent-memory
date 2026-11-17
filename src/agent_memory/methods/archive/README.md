# archive

Forget stage (`[forget] stages = ["archive"]`). Rules not fired in 30 days leave the always-loaded file.

- Every active rule with `now - last_used_at >= 30 days` is archived with `archived_at = now`. Used 29 days ago stays; unused for exactly 30 days is archived.
- A rule counts as used when a recall stage renders it: `tag_recall`, `rules_only` and `scored_recall` call `store.touch(ids, now)` for every entry they render or keep, which resets `last_used_at`.
- Facts and log lines are never touched here (facts follow `overwrite` and `expire`).
- Idempotent: a second run at the same `now` changes nothing, and a pass with nothing to archive writes no files. No LLM, no embedder; time comes only from `now`.

## When this fires

- The 28-day simulation is below the 30-day threshold, so `archive` cannot fire there. It does not run on LongMemEval.
- With no `[recall]` section the `rules_only` stand-in renders and touches all rules, so `archive` cannot fire from that either.
- `archive` fires only when the active recall stage leaves a rule unrendered:
  - `pool_route` plus `scored_recall`: rules go into `Routed.facts`, compete with facts and log for the top `TOP_K = 8`, and can rank below the cut.
  - `tag_recall` with a custom route that omits rules.
- `coala_stores` always includes every active rule, so it never triggers it.

Constants: `ARCHIVE_AFTER_DAYS = 30` in `stage.py`.
