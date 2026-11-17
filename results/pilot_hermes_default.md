# pilot - hermes_default

- date: 2026-11-17
- model: gpt-5.4-nano
- embedding model: none
- subset: first 3 tasks
- seed: 7
- tokens: 11165
- caveats: the pilot sends no corrections, plants no wrong rule and starts from an empty MEMORY.md, so the per-task figure is biased downward against a full 40-task run (memory and prompt grow over the run) | 6 runs = per run x 6 assumes hermes_default and hermes_no_memory cost the same; probably not true (memory off has a shorter prompt), so it is a rough planning number: run the pilot for hermes_no_memory too if it matters | the token cap is checked after each task, so one task can overshoot it | each Hermes call carries a fixed overhead (its system prompt and tools) even for a short task, measured in the real pilot (numbers in results/pilot_<config>.md and docs/hermes-flags.md), so a 40-task run needs a cap above the 100,000 per-config default; the spec allows raising the cap for Hermes only, `run` needs an explicit `--per-config-cap`
- extrapolation_1_run_per_config: 297734
- extrapolation_6_runs: 893202
- extrapolation_per_run_40_tasks: 148867
- failed_attempts: 0
- hermes_version: 0.23.2
- mean_tokens_per_task: 3722
- per_config_cap: 100000
- reproducibility: not cache-reproducible
- tasks: 3

## Metrics

- task 0:
  - tokens: 3742
  - words: 104
  - failed: False
- task 1:
  - tokens: 3726
  - words: 101
  - failed: False
- task 2:
  - tokens: 3697
  - words: 84
  - failed: False
