# overwrite

Forget stage (`[forget] stages = ["overwrite"]`). A new fact replaces the old one in place: for each key, one active line is kept.

- Facts are grouped by `slug(key)`, so `Booking Link` and `booking-link` are one key. Facts without a key are skipped.
- In a group with more than one active fact, the survivor keeps the id and `created_at` of the earliest fact, takes the text, tags, importance and `expires_at` of the newest (ties: later in store order), and gets `last_used_at = now`. The other facts are archived with `archived_at = now`.
- A group with one active fact is untouched. Rules, log lines and archived facts are never touched. No LLM, no embedder; time comes only from `now`.

When it matters: write stages that use `Store.upsert_fact` already collapse same-key facts at write time. This stage covers stages that use `Store.add`, and preloaded stores. It also runs on LongMemEval (knowledge updates), where expire, archive and reflect do not.

Constants: none.
