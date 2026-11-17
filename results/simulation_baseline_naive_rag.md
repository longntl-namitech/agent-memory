# simulation - baseline_naive_rag

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: text-embedding-3-small
- subset: all 40 tasks
- seed: 7
- tokens: 47528
- llm_cache: shared across configs, so per-config tokens depend on run order
- per_config_cap: 150000

## Metrics

- week 1:
  - corrections: 7
  - first_attempt_failures: 7
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 8456
- week 2:
  - corrections: 21
  - first_attempt_failures: 21
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 12959
- week 3:
  - corrections: 37
  - first_attempt_failures: 37
  - stale_fact_errors: 9
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 13029
- week 4:
  - corrections: 37
  - first_attempt_failures: 37
  - stale_fact_errors: 9
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 13084
