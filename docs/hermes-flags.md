# Hermes CLI flags check (Task 22)

Checked against Hermes Agent v0.23.2 (2026.9.24, stable, local commit ae2a81ccc00e), installed in the
isolated home `.hermes-home/` (always `export HERMES_HOME=<repo>/.hermes-home` first). Sources: `hermes --help`,
`hermes chat --help`, `hermes profile ... --help`, and the install checkout `$HERMES_HOME/hermes-agent`
(paths below are relative to it). No model call was made; the only state change was creating and then
deleting one throwaway profile (`hermes profile create tmpcheck`, `hermes profile delete tmpcheck -y`).
`~/.hermes` does not exist before or after.

## Findings from the first real calls

The first real `hermes -z` calls (gpt-5.4-nano through api.openai.com, key read into an environment variable only,
never printed or written) changed the adapter design. Facts:

1. **A named profile does not authenticate.** `-p NAME` (made by `hermes profile create`) is served through an
   auto-started gateway that never sees the calling process environment and reads keys only from the profile
   `.env` ("No API key for the custom endpoint ... not set for this profile"). The call exits 2 and writes a
   usage file whose token fields are `null`.
2. **A dedicated data root works.** `HERMES_HOME=<dir>` with a `config.yaml` we write (`model.default`,
   `provider: custom`, `base_url`, `key_env`, `agent.max_turns`, `memory.memory_enabled`,
   `memory.user_profile_enabled`), no `-p`, run as
   `hermes -z PROMPT --usage-file PATH --provider custom -m MODEL -t memory,file,skills,todo`: exit 0, the answer
   on stdout, a usage JSON with real numbers (`input_tokens` 6270, `output_tokens` 31, `total_tokens` 6301,
   `api_calls` 1, `completed` true, `failed` false, plus an `auxiliary` block), and the key read from the process
   environment only (nothing on disk).
3. **A new data root bootstraps its own runtime on first use** ("Preparing the isolated Hermes runtime...
   Installing Python dependencies", about 690 MB: `installs/` about 420 MB, `cache/` about 267 MB, slow). The data
   root must be reused across runs, not recreated per run.
4. **A call may auto-start a background gateway** (it exits after 600 s idle). Stop it with `hermes gateway stop`
   under the same `HERMES_HOME` (`hermes_cli/subcommands/gateway.py:181`).

Verified by these calls: the real usage JSON shape; exit 2 with null usage on a missing key; the key via the
environment works with a dedicated data root; `-t` accepted; `--provider custom` accepted. Still UNVERIFIED: exit
codes 1 and 130 in practice, `memory_enabled: false` removing the memory tool, a `memory` tool write by the model.

The adapter now uses one dedicated data root per config (`.hermes-lab/<config>`), no `-p`, no
`hermes profile create/delete`. The run state it wipes at start and at close, as paths under `$HERMES_HOME`, each
from the v0.23.2 sources: `memories/` (`tools/memory_tool.py:40`, MEMORY.md and USER.md), `sessions/`
(`hermes_state.py:452`, transcripts `sessions/<id>.jsonl`), `state.db*` (`hermes_state.py:184`, the session
database plus its `-wal` and `-shm` files), `checkpoints/` (`tools/checkpoint_manager.py:78`), `logs/`
(`agent.log` and others), `pending_messages/` (`gateway/shutdown_flush.py:47`), `response_store.db*`
(`gateway/platforms/api_server_response_store.py:61`), plus the adapter's own `workspace/` (the cwd of each call)
and `usage.json`. The runtime (`installs/`, `cache/`, the checkout and the rest) is kept.

Recommended argv now (after the first real calls): `HERMES_HOME=<data root> hermes -z PROMPT --usage-file PATH
--provider custom -m MODEL -t memory,file,todo` (`-t file,todo` for `hermes_no_memory`). The `skills` toolset is
dropped: emails need no skills, and skills the model writes would carry over between runs.

The sections below are the Task 22 check, written for the named-profile design; the profile parts are superseded.

## Loud findings (these change the design)

1. **DIFFERS, breaks the plan as written: `--ignore-user-config` also drops the profile's `config.yaml`
   memory keys.** With the flag the worker runs on a frozen snapshot of built-in defaults
   (`agent/safe_worker_policy.py:77`, `gateway/session_policy.py:450`, `hermes_cli/cli_config_load.py:271`).
   Defaults are `memory_enabled: true` and `user_profile_enabled: true`, so `hermes_no_memory` cannot be
   built from `config.yaml` + `--ignore-user-config`. The same flag also drops `model.base_url`, `model.provider`
   and `agent.max_turns` from the profile. It additionally refuses to start without an explicit `--model`
   (`hermes_cli/gateway_chat.py:105`). Since the throwaway profile is created fresh and its `config.yaml` is
   written by the adapter, there is no user config to ignore. Recommendation: do NOT pass
   `--ignore-user-config`; the fresh profile gives the same isolation. This needs the user to accept (grill Q30
   says "uses `--ignore-user-config`"); the intent (no leakage from the real user config) is still met.
2. **DIFFERS: no single command line carries every flag.** `--usage-file` exists only on the top-level parser
   (the `-z` path). `--max-turns` and `--base-url` exist only on `hermes chat`. So `hermes -z ... --max-turns`
   is an argparse error. Use `-z` with the usage file and set the turn cap in the profile `config.yaml`
   (`agent.max_turns`, built-in default 20) and the endpoint in `model.base_url`.
3. **UNVERIFIED until the pilot (T24):** the run itself (custom endpoint, `key_env`, usage file content,
   exit codes in practice). Also `hermes` printed `no dependency environment is committed for this install;
   run 'hermes pm repair'` on one invocation (a profile `config path` call). The install is the user's; I did
   not run repair. If T24 fails to start, that is the first thing to check.

Nothing the design depends on is MISSING.

## Item table

Verdict: OK / DIFFERS / MISSING. "Ran" is a command; other entries are file:line in the checkout.

| Item | Exists | Spelling | Evidence | Verdict |
|---|---|---|---|---|
| One-shot | yes | `hermes -z "PROMPT"` (top-level, same as `--oneshot PROMPT`) | `hermes --help`; `hermes_cli/_parser.py:146` | OK |
| Chat one-shot | yes | `hermes chat --oneshot -Q -q "PROMPT"`; `--oneshot` here is a boolean | `hermes chat --help` | OK (different from `-z`, see below) |
| Profile select | yes | `hermes -p NAME ...` or `--profile NAME`, pre-parsed before argparse, sets HERMES_HOME | `hermes_cli/_parser.py:14`, `main.py:343` | OK |
| `--ignore-user-config` | yes | `--ignore-user-config` (top-level and chat), env `HERMES_IGNORE_USER_CONFIG=1` | `hermes --help`; `main.py:2773` | DIFFERS (finding 1) |
| `--usage-file` | yes, top-level only | `--usage-file PATH`, `-z` only, "written even when the run fails" | `_parser.py:156`; `hermes_cli/oneshot.py:113` | OK, DIFFERS in placement (finding 2) |
| `-m` | yes | `-m, --model MODEL` (top-level and chat) | `hermes --help` | OK |
| `--provider` | yes | `--provider custom` (aliases `ollama`, `vllm`, `llamacpp` map to custom) | `hermes --help`; `cli-config.yaml.example:107` | OK |
| `--base-url` | chat only | `--base-url URL`, for `--provider custom` | `hermes chat --help` | DIFFERS (not on `-z`) |
| `--max-turns` | chat only | `--max-turns N` (default unlimited or `agent.max_turns`) | `hermes chat --help`; `_parser.py:303` | DIFFERS (not on `-z`) |
| Toolsets | yes | `-t, --toolsets a,b,c` (top-level, applies to `-z`; also on chat) | `hermes --help`; `oneshot.py:_normalize_toolsets` | OK |
| Leave out terminal | yes | list only wanted toolsets; names: `memory`, `file`, `skills`, `todo`, `session_search`, `web`, `terminal`, `safe` (no terminal) | `toolsets.py:72-170` | OK |
| `--ignore-rules` | yes | skips AGENTS.md, SOUL.md, .cursorrules, memory, preloaded skills | `hermes --help` | OK (confirms: do NOT use) |
| `--safe-mode` | yes | implies `--ignore-user-config` and `--ignore-rules` | `hermes --help`; `main.py:2762` | OK (do not use) |
| `memory_enabled`, `user_profile_enabled` | yes | `config.yaml` under `memory:`; default true; read by `get_builtin_memory_store_flags` | `tools/memory_tool.py:305-309`; `cli-config.yaml.example:1037-1050` | OK, but ignored under `--ignore-user-config` |
| Char caps | yes | `memory.memory_char_limit: 2200`, `memory.user_char_limit: 1375` | `tools/memory_tool_store.py:188`; example yaml 1049-1050 | OK |
| `memory` tool actions | yes | `add`, `patch`, `remove` (plus a batch form); `target` is `memory` or `user`; `patch` and `remove` need `old_text` | `tools/memory_tool.py:406-418,150` | OK |
| `-z` exit codes | yes | 0 completed, 2 failed/partial/`completed: False` (e.g. iteration budget), 130 interrupted, 1 completed with empty text | `hermes_cli/oneshot.py:83-101` | OK (as the spec says) |

## Profiles and directory layout (named profiles no longer used)

- `-p NAME` does NOT auto-create. For a missing profile it prints
  `Error: Profile 'nosuch' does not exist. Create it with: hermes profile create nosuch`
  (ran `hermes -p nosuch config path`; `hermes_cli/profiles.py:2342`).
- Create: `hermes profile create NAME --no-alias --no-skills --no-credentials` (ran; offline, no model call).
  `--no-alias` matters: without it a wrapper script is written into `~/.local/bin`. Without `--clone` no
  `config.yaml` is created, so the adapter writes it. Note the message "Logins and subscriptions are shared
  with the default profile": `--no-credentials` / `--isolated-auth` control that; keys should come from the
  environment instead (below).
- Delete: `hermes profile delete NAME -y` (ran; removes the whole directory, leaves an empty `profiles/`).
- Layout, relative to HERMES_HOME (the `.hermes-home` dir): `profiles/<name>/` holds `.env`, `SOUL.md`,
  `memories/`, `sessions/`, `skills/`, `cron/`, `home/`, `logs/`, `plans/`, `skins/`, `workspace/` (listed with `ls -a`
  after create). `config.yaml` appears when written.
- Memory files: `$HERMES_HOME/profiles/<name>/memories/MEMORY.md` and `.../memories/USER.md`
  (`tools/memory_tool.py:38`: `get_hermes_home() / "memories"`; `-p` re-homes HERMES_HOME to the profile dir).
  The spec's `~/.hermes/profiles/<name>/memories/` is right once `~/.hermes` is read as HERMES_HOME.
  Entries are separated by the delimiter `"\n§\n"` (`memory_tool_store.py:26`), so the adapter must write the
  planted rule and read entries with that delimiter. Memory is loaded once at session start (frozen snapshot).
- Root `$HERMES_HOME` (default profile) has its own `memories/`; throwaway runs never touch it when `-p` is used.

## Config and endpoint without interactive setup

Per-profile `profiles/<name>/config.yaml` written by the adapter:

```yaml
model:
  default: gpt-5.4-nano
  provider: custom
  base_url: https://<endpoint>/v1
  key_env: LAB_LLM_API_KEY   # NAME of an env var holding the key; no secret in the file
agent:
  max_turns: 20
memory:
  memory_enabled: true        # false for hermes_no_memory
  user_profile_enabled: true  # false for hermes_no_memory
```

- `model.default` (alias `model`), `model.provider`, `model.base_url` are in `cli-config.yaml.example:77-117`.
- `model.key_env` for a bare `provider: custom` is honoured only when the call's base URL equals
  `model.base_url` (`hermes_cli/runtime_provider_custom.py:68`). `OPENAI_API_KEY` / `OPENAI_BASE_URL` env vars are
  the alternative, but `OPENAI_API_KEY` is sent only to OpenAI hosts or to the host paired with `OPENAI_BASE_URL`
  (`runtime_provider.py:444-459`). Use `key_env`; export the key in the adapter's subprocess env only.
  UNVERIFIED until the pilot.
- `--api-key KEY` exists on `hermes chat` only; avoid it (key on the command line).
- Config and state are read from HERMES_HOME only (`hermes_constants.py:206`, `get_hermes_home`); `-p` sets it.
  `HOME` is not used for config when HERMES_HOME is set; the profile has its own `home/` dir for tool subprocesses.
  A different `HOME` is therefore expected to change nothing. UNVERIFIED at runtime; no reason to override it.

## How the adapter should call it (superseded: dedicated data root, see the findings above)

One task, one fresh profile, name unique per run (lowercase alphanumeric), e.g. `lab<runid>`. Same env for all steps:
`HERMES_HOME=<repo>/.hermes-home`, `LAB_LLM_API_KEY=<from the lab's own env>`.

1. Create: `hermes profile create lab<runid> --no-alias --no-skills --no-credentials`
2. Write `profiles/lab<runid>/config.yaml` (above; `memory_*: false` for `hermes_no_memory`). For the planted rule,
   write `profiles/lab<runid>/memories/MEMORY.md` before the first call (week 2).
3. Run (`hermes_default`):

```
hermes -p lab<runid> -z "<task prompt>" --provider custom -m gpt-5.4-nano \
  -t memory,file,skills,todo --usage-file <out>/lab<runid>.usage.json
```

   `hermes_no_memory`: same, with `-t file,skills,todo` (no `memory` toolset) and `memory_*: false` in the config.
   No `--ignore-rules`, no `--ignore-user-config` (finding 1), no `terminal` toolset. Turn cap comes from
   `agent.max_turns` in the profile config. If the user prefers a CLI cap, the alternative is
   `hermes -p lab<runid> chat --oneshot -Q -q "<prompt>" --provider custom -m gpt-5.4-nano -t ... --max-turns 20`
   but then the `--usage-file` path is UNVERIFIED (flag is top-level only; `hermes --usage-file P chat --oneshot ...`
   parses but whether the chat path writes it is unknown). Prefer `-z`.
4. Read the exit code (0 ok, 2 failed/partial, 130 interrupted, 1 empty) and the usage JSON; read
   `memories/MEMORY.md` and `USER.md` for the real-change count and size per week, before deleting.
5. Delete: `hermes profile delete lab<runid> -y` (in a `finally`). For safety also confirm `profiles/lab<runid>` is gone.

For long prompts or odd characters, `-z` takes the prompt as an argv string (pass argv as a list, no shell). Chat has
`--query-file PATH` as an alternative.

## Usage file format

`hermes_cli/oneshot.py:20-129`. JSON object, written even on failure, with keys: `estimated_cost_usd`, `cost_status`,
`cost_source`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`,
`total_tokens`, `api_calls`, `model`, `provider`, `session_id`, `completed`, `partial`, `interrupted`,
`turn_exit_reason`, `failed`, `service_tier`, optional `failure`, plus an `auxiliary` block (`input_tokens`, `output_tokens`, `total_tokens`, `api_calls`, `estimated_cost_usd`,
`by_task`) and `total_including_auxiliary` (`total_tokens`, `api_calls`, `estimated_cost_usd`)
(`oneshot.py:70-80`). Prompt tokens are `input_tokens`, completion tokens are `output_tokens`. For budget
accounting use `total_including_auxiliary.total_tokens`, because auxiliary calls (title generation, ...) also spend tokens.

## Unverified until the pilot (T24)

- VERIFIED (first real calls): the custom endpoint and `key_env` authenticate with a dedicated data root (not with
  a named profile).
- VERIFIED (first real calls): the usage file is written by `hermes -z` and has the keys above, including on a
  failed call (token fields `null`).
- Real exit codes for a budget stop (`agent.max_turns`) and for an empty reply (1), and for an interrupt (130).
- `memory_enabled: false` really removes the `memory` tool and the MEMORY.md block from the system prompt
  (code reads the flag at `memory_tool.py:305-309`; not exercised).
- `-t memory,file,todo` leaves no terminal access (the flag is accepted; toolset contents read, not run).
- A `memory` tool write (`add`, `patch`) made by the model in a real run.
- That the `hermes pm repair` notice does not block a real run.
