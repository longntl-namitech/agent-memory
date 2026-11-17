# write_filter

Write stage. One LLM call per event (`purpose="write_filter"`), except a `correction` whose normalised text this instance has already turned into a rule outcome (rule stored, duplicate of an active rule, or dropped at the cap): it returns nothing and makes no call. The LLM call returns JSON with `kind` (rule|fact|log), `key` (facts), `importance` (1-10) and `text` (the distilled lesson, never the raw event). The prompt lists the existing fact keys so the model reuses one.

- Rules go through `store.add`; an active rule with the same normalised text (lowercase, collapsed whitespace) is skipped, and so is any new rule when `MAX_RULES` (20) are active (counted in the instance attribute `dropped_rules`).
- Facts go through `store.upsert_fact`, so `Booking Link` and `booking-link` are one entry.
- Logs go through `store.add`.
- Entries get `created_at = last_used_at = now`, `expires_at = None`. Entry tags are the event tags only; the prompt does not ask for tags and any in a reply are ignored. A `rule` is honoured only for `correction` events, otherwise it is stored as a log line.
- Invalid JSON, an unknown kind, empty text or a fact without a key: the event text is written as one log line (no retry) and the instance attribute `fallbacks` is incremented.

Constants: `MAX_RULES = 20` (from layout), default importance 5 (also used when the reply's is missing or non-numeric), importance clamped to 1-10.
