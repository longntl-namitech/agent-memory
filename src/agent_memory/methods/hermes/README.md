# hermes

Whole-agent baseline: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT, Nous Research) runs the
simulation as an outside agent, so its own learning loop (the `memory` tool and `MEMORY.md`) can be compared with
the stage stack. Simulation only, no LongMemEval row. Configs: `hermes_default` and `hermes_no_memory` (the
control, built-in stores off). Checked against Hermes v0.23.2, see `docs/hermes-flags.md`.

## Adapter flow

- One profile per run. The first call (`run_task`, `plant_rule`) creates it with
  `hermes profile create NAME --no-alias --no-skills --no-credentials` and writes its `config.yaml`:
  model, `provider: custom`, `base_url`, `key_env`, `agent.max_turns`, and `memory_enabled` /
  `user_profile_enabled` (both `false` for `hermes_no_memory`). `close()` runs `hermes profile delete NAME -y`
  and then removes the directory if it is still there.
- One fresh session per task:
  `hermes -p NAME -z PROMPT --usage-file PATH --provider custom -m MODEL -t memory,file,skills,todo`
  (`-t file,skills,todo` without memory). The prompt is the lab's own task text (`TASK_PROMPT` plus the lead
  JSON, shared with MemoryAgent), then the corrections received since the last task as user text. Memory persists across tasks only through the profile.
- Exit codes: 0 is the email. 2 (failed or partial) and 1 (no text) are failed attempts: `output` is `""`,
  `failed_check` is `hermes_failed` and `failed_attempts` goes up; the runner scores the empty output against the
  active rules, so it counts as violations, never as a passing email. A failed attempt does not stop the run.
  130 (interrupted), any other code, a subprocess timeout or a missing usage file raise `HermesError`, which aborts
  the run with a partial result.
- Tokens come from the usage file: `total_including_auxiliary.total_tokens`, else `total_tokens`, else input plus
  output. They are spent on the run's `TokenBudget` after each task, so the per-config cap is enforced on Hermes's
  own usage (`BudgetExceeded`, partial result). `receive_correction`, `end_task` and `reflect` spend 0.
- `MEMORY.md` plumbing for the simulation: `plant_rule` appends an entry (delimiter `\n§\n`). It is never
  refused: if the file would pass its 2,200-character cap, the rule is planted anyway, none of Hermes' own entries
  are deleted, and the result records `planted_over_cap: true` (`false` otherwise). What Hermes does with a file
  over its cap is verified by the T24 pilot; `review(blocklist)` removes every entry holding a marker, case and whitespace ignored, so
  a rule Hermes rewrote with `patch` is still caught. `agent.store` (`MemoryMdStore`) gives the runner and the
  Monday Reviewer the `add` / `rules` / `all_rules` / `archive` surface over the same file, so the real file
  changes are what is counted. `memory_size()` is the file's character count, recorded at each Friday reflect
  (`memory_size_per_week` in the result).
- `USER.md` is not planted into or reviewed.

## Isolation

- `HERMES_HOME` is the isolated `profile_root` (`.hermes-home`), never `~/.hermes`. A relative `profile_root`
  is taken from the repo root, not the cwd. A missing binary raises `HermesError` naming the binary and PATH.
- No `--ignore-user-config`: it freezes built-in defaults, which would ignore `memory_enabled: false` and the
  endpoint in the profile config. The fresh profile with an adapter-written `config.yaml` gives the same isolation.
- No `--ignore-rules`: it also skips memory, the thing under test. No `terminal` toolset.
- The API key stays in the environment variable named by `key_env`. It is never written to `config.yaml`, put on
  the command line or logged.
- The profile is deleted in `close()`; the runner calls it in a `finally`, so a crash or a budget stop leaves no
  profile behind.

## Reproducibility

Hermes calls the model itself and reads real time, so its runs are not cache-reproducible. The result records the
Hermes version (`hermes --version`), `failed_attempts`, `planted_over_cap` and
`memory_size_per_week`. With memory off (`hermes_no_memory`) `extra_from_wrong_rule` is `n/a`, as for the
whole-memory baselines: no MEMORY.md is loaded, so the planted rule never reaches the prompt. The number of runs and their
spread are filled by the pilot (T24).

## Unverified until the pilot (T24)

- That the custom endpoint and `key_env` authenticate (`key_env` defaults to `OPENAI_API_KEY`, `base_url` to
  `$OPENAI_BASE_URL`).
- That `hermes -z` writes the usage file with the keys above, and its real exit codes for a turn-cap stop and an
  empty reply.
- That stdout of `hermes -z` is the email text only.
- That `memory_enabled: false` removes the memory tool and block, and that `-t` leaves no terminal access.
- That a `MEMORY.md` written by the adapter (entries joined by `\n§\n`, nothing else) is read by Hermes as is.
- That the `hermes pm repair` notice seen once does not block a real run.

All tests run against `tests/fixtures/fake_hermes.sh`, a stub; nothing here has called the real binary.
