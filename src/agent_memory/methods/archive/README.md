# archive

Forget stage (`[forget] stages = ["archive"]`). Rules not fired in 30 days leave the always-loaded file.

- Every active rule with `now - last_used_at >= 30 days` is archived with `archived_at = now`. Used 29 days ago stays; unused for exactly 30 days is archived.
- A rule counts as used when a recall stage renders it: `tag_recall` and `rules_only` call `store.touch(ids, now)` for every rendered entry, which resets `last_used_at`.
- Facts and log lines are never touched here (facts follow `overwrite` and `expire`).
- Idempotent: a second run at the same `now` changes nothing, and a pass with nothing to archive writes no files. No LLM, no embedder; time comes only from `now`.

## When this fires

The simulation spans 4 weeks (28 days), below the 30-day threshold, so `archive` cannot fire there. It does not run on LongMemEval.

In longer runs it only fires for rules that no recall stage renders, which happens:

- in configs with no recall stage;
- with `pool_route` plus `scored_recall`, when a rule scores below the top 8 (`TOP_K = 8`): it is neither rendered nor touched.

Constants: `ARCHIVE_AFTER_DAYS = 30` in `stage.py`.
