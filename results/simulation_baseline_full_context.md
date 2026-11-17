# simulation - baseline_full_context

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: all 40 tasks
- seed: 7
- tokens: 15645
- llm_cache: shared across configs, so per-config tokens depend on run order
- per_config_cap: 250000

## Metrics

- week 1:
  - corrections: 0
  - first_attempt_failures: 0
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 0
- week 2:
  - corrections: 1
  - first_attempt_failures: 1
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 0
- week 3:
  - corrections: 5
  - first_attempt_failures: 5
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 0
- week 4:
  - corrections: 5
  - first_attempt_failures: 5
  - stale_fact_errors: 0
  - extra_from_wrong_rule: n/a (baseline has no RULES)
  - tokens: 15645
