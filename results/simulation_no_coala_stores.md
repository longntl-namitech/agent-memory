# simulation - no_coala_stores

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 105161
- llm_cache: shared across configs, so per-config tokens depend on run order
- note: corrections are counted after an oracle-guided retry; compare memory methods on first_attempt_failures
- per_config_cap: 150000
- reflect_failures: 0
- reflexion_fallbacks: 0
- write_filter_dropped_rules: 0
- write_filter_fallbacks: 0

## Metrics

- week 1:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 8350
- week 2:
  - corrections: 9
  - first_attempt_failures: 9
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 9
  - tokens: 30408
- week 3:
  - corrections: 9
  - first_attempt_failures: 9
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 31738
- week 4:
  - corrections: 10
  - first_attempt_failures: 9
  - stale_fact_errors: 1
  - extra_from_wrong_rule: 0
  - tokens: 34665
