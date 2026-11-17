# simulation - b1_write_filter

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 20861
- llm_cache: shared across configs, so per-config tokens depend on run order
- per_config_cap: 150000
- write_filter_dropped_rules: 0
- write_filter_fallbacks: 1

## Metrics

- week 1:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 2557
- week 2:
  - corrections: 9
  - first_attempt_failures: 9
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 9
  - tokens: 5836
- week 3:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 6219
- week 4:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 6249
