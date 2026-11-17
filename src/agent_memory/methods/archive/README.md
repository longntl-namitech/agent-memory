# archive

Forget stage (`[forget] stages = ["archive"]`). Rules not fired in 30 days leave the always-loaded file.

- Every active rule with `now - last_used_at >= 30 days` is archived with `archived_at = now`. Used 29 days ago stays; unused for exactly 30 days is archived.
- A rule counts as used when a recall stage renders it: `tag_recall` and `rules_only` call `store.touch(ids, now)` for every rendered entry, which resets `last_used_at`.
- Facts and log lines are never touched here (facts follow `overwrite` and `expire`).
- Idempotent: a second run at the same `now` changes nothing, and a pass with nothing to archive writes no files. No LLM, no embedder; time comes only from `now`.

## When this fires

The simulation spans 4 weeks (28 days), below the 30-day threshold, so `archive` cannot fire at all in it. It does not run on LongMemEval.

Beyond that, every recall stage renders all active rules each task and touches them, so a rule that is always loaded never ages out. With recall stages that always render RULES, `archive` only fires for rules a recall stage does not render, for example configs with no recall stage, or a rule the route excluded.

Constants: `ARCHIVE_AFTER_DAYS = 30` in `stage.py`.
