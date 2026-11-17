# write_raw

Write stage stand-in, used when a config has no `[write]` stage. No LLM call: the event text becomes one log entry (tags from the event, importance 5, `created_at = last_used_at = now`, `expires_at = None`).

Constants: importance 5.
