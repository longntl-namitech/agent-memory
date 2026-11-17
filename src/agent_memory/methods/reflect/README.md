# reflect

Reflect stage, run by the simulation on Friday after the last task (and by the same hook weekly). One LLM call (`purpose="reflect"`) reads the active log lines and the active rules and returns JSON: `{"rules": [{"text", "importance", "sources"}]}`.

- Registered as kind `reflect`. At most `MAX_NEW_RULES = 3` rules are kept per call (the first 3 if the model returns more).
- Each rule is stored via `store.add` as kind `rule`, tags `["global"]`, `created_at = last_used_at = now`, importance clamped to 1-10 (default 5).
- `sources` are log ids; only ids of active log lines are archived (`store.archive(id, now)`), unknown ids are ignored.
- Dedupe: a rule whose lowercase, whitespace-collapsed text equals an active rule is skipped. A duplicate archives nothing, not even its source lines.
- Cap (decision A2): when adding would exceed `MAX_RULES = 20` active rules, the least valuable active rules are archived first (lowest importance, then oldest `last_used_at`, then oldest `created_at`, then insertion order in `all_rules()`, never the id string), only as many as needed, never one added in the same pass. `RulesFull` never leaves `reflect`.
- No active log lines: no LLM call. Invalid JSON, wrong shape, or a non-empty `rules` list with no usable item (e.g. plain strings): nothing is changed and the per-instance `failures` counter is incremented. Unusable items inside a valid list are skipped. `BudgetExceeded` and transport errors propagate.
- Time only from `now`.

Constants: `MAX_NEW_RULES = 3`, `MAX_RULES = 20` (from layout), default importance 5.
