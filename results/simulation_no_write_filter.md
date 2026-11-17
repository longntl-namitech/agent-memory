# simulation - no_write_filter

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 63382
- llm_cache: shared across configs, so per-config tokens depend on run order
- note: corrections are counted after an oracle-guided retry; compare memory methods on first_attempt_failures
- per_config_cap: 150000
- reflect_failures: 0
- reflexion_fallbacks: 0

## Metrics

- week 1:
  - corrections: 1
  - first_attempt_failures: 5
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 9746
- week 2:
  - corrections: 10
  - first_attempt_failures: 10
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 9
  - tokens: 15690
- week 3:
  - corrections: 3
  - first_attempt_failures: 10
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 23078
- week 4:
  - corrections: 1
  - first_attempt_failures: 1
  - stale_fact_errors: 0
  - extra_from_wrong_rule: 0
  - tokens: 14868
