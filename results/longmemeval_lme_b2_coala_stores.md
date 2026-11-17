# longmemeval - lme_b2_coala_stores

- date: 2026-11-18
- model: gpt-5.4-nano
- embedding model: none
- subset: 8 questions (2 information extraction, 2 multi-session reasoning, 2 knowledge updates, 1 temporal reasoning, 1 abstention) from the 50 selected
- seed: 7
- tokens: 0
- judge: gpt-5.4-nano LLM judge (LongMemEval prompts), not comparable with the official GPT-4o judge
- llm_cache: shared across configs, so per-config tokens depend on run order

## Metrics

| ability | correct | total | accuracy |
| --- | --- | --- | --- |
| information extraction | 0 | 2 | 0% |
| multi-session reasoning | 0 | 2 | 0% |
| knowledge updates | 0 | 2 | 0% |
| temporal reasoning | 0 | 1 | 0% |
| abstention | 1 | 1 | 100% |
| all | 1 | 8 | 12% |
