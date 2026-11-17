# hermes

Whole-agent baseline: [Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT, Nous Research) runs the
simulation as an outside agent, so its own learning loop (the `memory` tool and `MEMORY.md`) can be compared with
the stage stack. Simulation only, no LongMemEval row. Configs: `hermes_default` and `hermes_no_memory` (the
control, built-in stores off). Checked against Hermes v0.23.2, see `docs/hermes-flags.md`.

## Adapter flow

- One dedicated Hermes data root per config: `profile_root` is the `HERMES_HOME` of that agent
  (`.hermes-lab/hermes_default`, `.hermes-lab/hermes_no_memory`, gitignored). No named profile, no `-p`, no
  `hermes profile create/delete`: the first real calls showed a named profile is served by a gateway that never
  sees our environment, so the key would have to be written into the profile `.env`.
- The data root is reused across runs. Its first use bootstraps Hermes' own runtime (about 690 MB, slow:
  "Preparing the isolated Hermes runtime... Installing Python dependencies"), so it is paid once per config.
- Reset at `start()` (the first `run_task` or `plant_rule`): wipe the run state, then write `config.yaml` (always
  overwritten): model, `provider: custom`, `base_url`, `key_env`, `agent.max_turns`, and `memory_enabled` /
  `user_profile_enabled` (both `false` for `hermes_no_memory`). The run state is `memories/`, `sessions/`,
  `state.db*`, `checkpoints/`, `logs/`, `pending_messages/`, `response_store.db*`, `spawn-ledger.json*` (each call's argv, prompt included), plus the
  adapter's `workspace/` (the cwd of each call) and `usage.json` (paths checked in `docs/hermes-flags.md`). The runtime
  (`installs/`, `cache/` and the rest) is kept. Because the reset runs at start, a run killed before `close()`
  does not leak its memory into the next run. Other stores that could hold content (`cron/`, `kanban.db`,
  `projects.db`, `plans/`, `tmp/`) are not wiped: the only toolsets passed are `memory` (writes `memories/`) and
  `todo`, so the model has no tool that writes there.
- `close()` runs `hermes gateway stop` under the same `HERMES_HOME` (a call may auto-start a background gateway;
  a failure or a timeout of the stop is ignored), then wipes the run state again: no memory or session content
  is left behind after a success, a failure or a crash. The runtime stays.
- The version for the result header comes from `hermes --version` run with `HERMES_HOME` set to the install home
  (`install_home`, default `.hermes-home`, taken from the repo root), not the data root: `--version` exits 1
  ("no dependency environment ... run 'hermes pm repair'") in a data root `-z` has not bootstrapped yet. A failing
  `--version` records `unknown (hermes --version exited N)` and the run goes on. Apart from `-z`, the only call on
  the data root is `gateway stop`, whose failure is ignored.
- One fresh session per task:
  `HERMES_HOME=<data root> hermes -z PROMPT --usage-file PATH --provider custom -m MODEL -t memory,todo`
  (`-t todo` without memory). No `skills`, `file` or `terminal` toolset: an email needs none of them; skills the
  model writes would carry over between runs (the data root keeps `skills/`), and Hermes v0.23.2's file write
  guard only blocks sensitive system paths, so `file` could write outside the wiped state and read the repo
  (corrections, blocklist, earlier results). The prompt is the lab's own task text (`TASK_PROMPT` plus the lead
  JSON, shared with MemoryAgent), then the corrections received since the last task as user text. Memory persists
  across the tasks of a run only through `<data root>/memories/MEMORY.md`.
- Exit codes: 0 is the email. 2 (failed or partial) and 1 (no text) are failed attempts: `output` is `""`,
  `failed_check` is `hermes_failed` and `failed_attempts` goes up; the runner scores the empty output against the
  active rules, so it counts as violations, never as a passing email. A failed attempt does not stop the run.
  130 (interrupted), any other code, a subprocess timeout or a missing usage file raise `HermesError`, which aborts
  the run with a partial result.
- Tokens come from the usage file: `total_including_auxiliary.total_tokens`, else `total_tokens`, else input plus
  output, with `null` read as 0 (a failed call writes every token field as `null`; it counts 0 tokens and is a
  failed attempt, not a crash). A missing usage file on exit 0 still raises `HermesError`. They are spent on the run's `TokenBudget` after each task, so the per-config cap is enforced on Hermes's
  own usage (`BudgetExceeded`, partial result). `receive_correction`, `end_task` and `reflect` spend 0.
- `MEMORY.md` plumbing for the simulation (`<data root>/memories/MEMORY.md`): `plant_rule` appends an entry (delimiter `\n§\n`). It is never
  refused: if the file would pass its 2,200-character cap, the rule is planted anyway, none of Hermes' own entries
  are deleted, and the result records `planted_over_cap: true` (`false` otherwise). What Hermes does with a file
  over its cap is UNVERIFIED; `review(blocklist)` removes every entry holding a marker, case and whitespace ignored, so
  a rule Hermes rewrote with `patch` is still caught. `agent.store` (`MemoryMdStore`) gives the runner and the
  Monday Reviewer the `add` / `rules` / `all_rules` / `archive` surface over the same file, so the real file
  changes are what is counted. `memory_size()` is the file's character count, recorded at each Friday reflect
  (`memory_size_per_week` in the result).
- `USER.md` (`<data root>/memories/USER.md`) is not planted into or reviewed; it is wiped with the run state.

## Isolation

- `HERMES_HOME` is always forced to the config's data root in the subprocess environment, never `~/.hermes`.
  A relative `profile_root` is taken from the repo root, not the cwd; run the commands from the repo root anyway.
  A missing binary raises `HermesError` naming the binary and PATH.
- No `--ignore-user-config`: it freezes built-in defaults, which would ignore `memory_enabled: false` and the
  endpoint in `config.yaml`. The dedicated data root with an adapter-written `config.yaml` gives the same isolation.
- No `--ignore-rules`: it also skips memory, the thing under test. No `terminal`, `file` or `skills` toolset.
- The API key stays in the environment variable named by `key_env`. It is never written to `config.yaml` or
  any other file, put on the command line or logged.
- `close()` runs in a `finally` in the runner and in the pilot, so a crash or a budget stop also stops the gateway
  and leaves no memory or session content behind. Only the runtime stays in `.hermes-lab/`.

## Reproducibility

Hermes calls the model itself and reads real time, so its runs are not cache-reproducible. The result records the
Hermes version (`hermes --version`), `failed_attempts`, `planted_over_cap` and
`memory_size_per_week`. With memory off (`hermes_no_memory`) `extra_from_wrong_rule` is `n/a`, as for the
whole-memory baselines: no MEMORY.md is loaded, so the planted rule never reaches the prompt. The 3-runs spread is not produced
by the pilot (it runs one config for a few tasks); it needs the real runs.

## Verified and unverified

Verified by the real calls and pilots (see `docs/hermes-flags.md`): the key via the process environment
(`key_env`, default `OPENAI_API_KEY`; `base_url` defaults to `$OPENAI_BASE_URL`) works with a dedicated data root;
a failed call (exit 2, missing key) writes a usage file with `null` token fields; `-t memory,file,todo` and
`-t memory,todo` are accepted; `--provider custom` is accepted; the real usage JSON shape; wipe-then-reuse of a
data root, once, without a re-bootstrap; `gateway stop` leaves no Hermes process behind; no key on disk.

Measured on 2026-11-17 by the second real pilot (3 tasks of `hermes_default`, toolsets `memory,todo`): 3,715 /
3,719 / 3,758 tokens per task (mean 3,731), 0 failed attempts; extrapolated 149,227 per 40-task run, 895,362 for 6
runs (2 configs x 3), 298,454 for 1 run per config. The recommended per-config cap for a Hermes run is at least
about 150,000 plus headroom for growth: the figure is a downward-biased lower bound (no corrections, no planted
rule, empty MEMORY.md). `run` refuses a Hermes config without an explicit `--per-config-cap` (the spec allows
raising it for Hermes only).

Still unverified:

- The real exit codes 1 (empty reply) and 130 (interrupt), and the code for a turn-cap stop.
- A memory write (`add`, `patch`) made by the model in a real run (the pilot tasks wrote none that we checked).
- What Hermes does with a MEMORY.md above its 2,200-character cap.
- Recovery from a partial bootstrap.
- The 3-run spread (the pilot does not produce it).
- That stdout of `hermes -z` is the email text only.
- That `memory_enabled: false` removes the memory tool and block, and that `-t` leaves no terminal or file
  access.
- That a `MEMORY.md` written by the adapter (entries joined by `\n§\n`, nothing else) is read by Hermes as is.

All tests run against `tests/fixtures/fake_hermes.sh`, a stub; nothing here has called the real binary.
