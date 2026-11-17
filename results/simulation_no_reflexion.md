# simulation - no_reflexion

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 0
- llm_cache: shared across configs, so per-config tokens depend on run order
- per_config_cap: 150000
- reflect_failures: 0
- write_filter_dropped_rules: 0
- write_filter_fallbacks: 0

## Metrics

- week 1:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 0
- week 2:
  - corrections: 10
  - first_attempt_failures: 10
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 9
  - tokens: 0
- week 3:
  - corrections: 3
  - first_attempt_failures: 3
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 0
- week 4:
  - corrections: 4
  - first_attempt_failures: 4
  - stale_fact_errors: 1
  - extra_from_wrong_rule: 0
  - tokens: 0
