# simulation - hermes_no_memory

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 141230
- failed_attempts: 0
- hermes_version: 0.23.2
- memory_size_per_week: {'week 1': 0, 'week 2': 65, 'week 3': 0, 'week 4': 0}
- per_config_cap: 250000
- planted_over_cap: False
- reproducibility: not cache-reproducible

## Metrics

- week 1:
  - corrections: 3
  - first_attempt_failures: 3
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 34175
- week 2:
  - corrections: 11
  - first_attempt_failures: 11
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 34415
- week 3:
  - corrections: 21
  - first_attempt_failures: 21
  - stale_fact_errors: 5
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 30965
- week 4:
  - corrections: 14
  - first_attempt_failures: 14
  - stale_fact_errors: 4
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 41675
