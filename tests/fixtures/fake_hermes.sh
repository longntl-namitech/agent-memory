#!/bin/bash
# Stub of the `hermes` CLI (v0.23.2 surface) for tests: no model, no network, writes only under $HERMES_HOME.
# It emulates a dedicated data root (HERMES_HOME, no -p): the first use "bootstraps" installs/ (the heavy runtime
# the adapter must keep); a -z run writes run state the adapter must wipe (a session transcript, state.db and a
# log line and spawn-ledger.json, all holding the prompt) and marks the background gateway as running; `gateway stop` stops it.
# `--version` exits 1 ("no dependency environment") in a home without installs/; only -z bootstraps.
# A -z run whose config.yaml names a key_env that is unset exits 2 with an all-null usage file (the real failure).
# Behaviour comes from env vars:
#   FAKE_HERMES_LOG             append each call's argv (fields split by \x1f, records end with \x1e)
#   FAKE_HERMES_HOME_LOG        append the HERMES_HOME each call saw, one per line
#   FAKE_HERMES_EXIT            exit code of a -z run (default 0); 1 prints no text
#   FAKE_HERMES_OUTPUT          text printed by a -z run
#   FAKE_HERMES_INPUT_TOKENS / FAKE_HERMES_OUTPUT_TOKENS / FAKE_HERMES_AUX_TOKENS   usage numbers
#   FAKE_HERMES_USAGE_JSON      write this JSON verbatim as the usage file
#   FAKE_HERMES_NO_USAGE        set: write no usage file
#   FAKE_HERMES_MEMORY_ADD      the model "calls memory add": append an entry to MEMORY.md
#   FAKE_HERMES_PATCH_OLD/NEW   the model "calls memory patch": replace text in MEMORY.md
#   FAKE_HERMES_SLEEP           a -z run hangs this many seconds (timeout tests)
#   FAKE_HERMES_SLEEP_AFTER_USAGE   a -z run hangs this many seconds after writing its usage file
#   FAKE_HERMES_GATEWAY_EXIT / FAKE_HERMES_GATEWAY_SLEEP   exit code of / hang in `gateway stop`
set -u

if [ -n "${FAKE_HERMES_LOG:-}" ]; then
  { printf '%s\037' "$@"; printf '\036'; } >> "$FAKE_HERMES_LOG"
fi
if [ -n "${FAKE_HERMES_HOME_LOG:-}" ]; then
  printf '%s\n' "${HERMES_HOME:-}" >> "$FAKE_HERMES_HOME_LOG"
fi

if [ "${1:-}" = "--version" ]; then  # like the real one: needs a home whose runtime is already bootstrapped
  if [ ! -d "${HERMES_HOME:-/nonexistent}/installs" ]; then
    echo "hermes: no dependency environment is committed for this install; run 'hermes pm repair'" >&2
    exit 1
  fi
  echo "Hermes Agent v0.23.2 (2026.9.24)"
  exit 0
fi

: "${HERMES_HOME:?HERMES_HOME must be set}"

if [ ! -d "$HERMES_HOME/installs" ]; then  # the one-time runtime bootstrap of a new data root
  mkdir -p "$HERMES_HOME/installs"
  echo bootstrap >> "$HERMES_HOME/installs/bootstrap.log"
fi

if [ "${1:-}" = "gateway" ] && [ "${2:-}" = "stop" ]; then
  [ -n "${FAKE_HERMES_GATEWAY_SLEEP:-}" ] && sleep "$FAKE_HERMES_GATEWAY_SLEEP"
  printf '{"gateway_state": "stopped"}\n' > "$HERMES_HOME/gateway_state.json"
  exit "${FAKE_HERMES_GATEWAY_EXIT:-0}"
fi

prompt="" usage=""
while [ $# -gt 0 ]; do
  case "$1" in
    -z) prompt=$2; shift 2;;
    --usage-file) usage=$2; shift 2;;
    -m|-t|--provider) shift 2;;
    *) echo "fake hermes: unknown argument $1" >&2; exit 2;;
  esac
done

if [ -n "${FAKE_HERMES_SLEEP:-}" ]; then
  exec sleep "$FAKE_HERMES_SLEEP"
fi

printf '{"gateway_state": "running"}\n' > "$HERMES_HOME/gateway_state.json"
mkdir -p "$HERMES_HOME/sessions" "$HERMES_HOME/logs"
printf '{"role": "user", "content": %s}\n' "\"$prompt\"" >> "$HERMES_HOME/sessions/session_fake.jsonl"
printf '%s\n' "$prompt" >> "$HERMES_HOME/state.db"
printf 'turn: %s\n' "$prompt" >> "$HERMES_HOME/logs/agent.log"
printf '[{"pid": %d, "argv": ["-z", "%s"]}]\n' $$ "$prompt" > "$HERMES_HOME/spawn-ledger.json"
: > "$HERMES_HOME/spawn-ledger.json.lock"

key_env=$(sed -n 's/^  key_env: "\(.*\)"$/\1/p' "$HERMES_HOME/config.yaml" 2>/dev/null)
if [ -n "$key_env" ] && [ -z "${!key_env:-}" ]; then
  echo "No API key for the custom endpoint: $key_env is not set" >&2
  [ -n "$usage" ] && printf '{"input_tokens": null, "output_tokens": null, "total_tokens": null, "api_calls": 0, "completed": false, "failed": true, "total_including_auxiliary": {"total_tokens": null, "api_calls": 0}}\n' > "$usage"
  exit 2
fi

mem="$HERMES_HOME/memories/MEMORY.md"
if [ -n "${FAKE_HERMES_PATCH_OLD:-}" ] && [ -f "$mem" ]; then
  content=$(cat "$mem")
  old=$FAKE_HERMES_PATCH_OLD new=${FAKE_HERMES_PATCH_NEW:-}
  printf '%s' "${content//"$old"/$new}" > "$mem"
fi
if [ -n "${FAKE_HERMES_MEMORY_ADD:-}" ]; then
  mkdir -p "$HERMES_HOME/memories"
  if [ -s "$mem" ]; then printf '\n\302\247\n%s' "$FAKE_HERMES_MEMORY_ADD" >> "$mem"
  else printf '%s' "$FAKE_HERMES_MEMORY_ADD" > "$mem"; fi
fi

if [ -n "$usage" ] && [ -z "${FAKE_HERMES_NO_USAGE:-}" ]; then
  if [ -n "${FAKE_HERMES_USAGE_JSON:-}" ]; then
    printf '%s\n' "$FAKE_HERMES_USAGE_JSON" > "$usage"
  else
    in=${FAKE_HERMES_INPUT_TOKENS:-1000} out=${FAKE_HERMES_OUTPUT_TOKENS:-200} aux=${FAKE_HERMES_AUX_TOKENS:-50}
    printf '{"input_tokens": %d, "output_tokens": %d, "total_tokens": %d, "api_calls": 1, "completed": true, "failed": false, "auxiliary": {"total_tokens": %d, "api_calls": 1}, "total_including_auxiliary": {"total_tokens": %d, "api_calls": 2}}\n' \
      "$in" "$out" $((in + out)) "$aux" $((in + out + aux)) > "$usage"
  fi
fi

if [ -n "${FAKE_HERMES_SLEEP_AFTER_USAGE:-}" ]; then
  exec sleep "$FAKE_HERMES_SLEEP_AFTER_USAGE"
fi

code=${FAKE_HERMES_EXIT:-0}
if [ "$code" != 1 ]; then
  printf '%s\n' "${FAKE_HERMES_OUTPUT-Hello from the fake hermes.}"
fi
exit "$code"
