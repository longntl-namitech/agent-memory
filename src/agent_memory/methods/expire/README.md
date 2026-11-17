# expire

Forget stage (`[forget] stages = ["expire"]`). One-off notes get a date and disappear after 7 days.

- One-off notes are the active log lines. The first time `expire` sees a log line with no `expires_at`, it sets `expires_at = created_at + 7 days` and saves it. An `expires_at` that is already set is never changed.
- Any active log line or fact whose `expires_at` is set and `now >= expires_at` is archived with `archived_at = now`. So a line is active at 6 days and archived at exactly 7 days.
- Rules are never expired here (the `archive` stage handles unused rules). Facts expire only if their `expires_at` was set explicitly.
- Idempotent: a second run at the same `now` changes nothing, and a pass with nothing to do writes no files. No LLM, no embedder; time comes only from `now`.

When it matters: it does not run on LongMemEval, where facts must stay available across long histories.

Constants: `EXPIRY_DAYS = 7` in `stage.py`.
