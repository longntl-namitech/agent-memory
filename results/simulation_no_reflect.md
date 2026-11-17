# simulation - no_reflect

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 27302
- llm_cache: shared across configs, so per-config tokens depend on run order
- note: corrections are counted after an oracle-guided retry; compare memory methods on first_attempt_failures
- per_config_cap: 150000
- reflexion_fallbacks: 0
- write_filter_dropped_rules: 0
- write_filter_fallbacks: 1

## Metrics

- week 1:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 0
- week 2:
  - corrections: 8
  - first_attempt_failures: 9
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 8
  - tokens: 11854
- week 3:
  - corrections: 1
  - first_attempt_failures: 2
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 7251
- week 4:
  - corrections: 0
  - first_attempt_failures: 1
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 8197
