#!/bin/bash
# Stub of the `hermes` CLI (v0.23.2 surface) for tests: no model, no network, writes only under $HERMES_HOME.
# Behaviour comes from env vars:
#   FAKE_HERMES_LOG             append each call's argv (fields split by \x1f, records end with \x1e)
#   FAKE_HERMES_EXIT            exit code of a -z run (default 0); 1 prints no text
#   FAKE_HERMES_OUTPUT          text printed by a -z run
#   FAKE_HERMES_INPUT_TOKENS / FAKE_HERMES_OUTPUT_TOKENS / FAKE_HERMES_AUX_TOKENS   usage numbers
#   FAKE_HERMES_USAGE_JSON      write this JSON verbatim as the usage file
#   FAKE_HERMES_NO_USAGE        set: write no usage file
#   FAKE_HERMES_MEMORY_ADD      the model "calls memory add": append an entry to MEMORY.md
#   FAKE_HERMES_PATCH_OLD/NEW   the model "calls memory patch": replace text in MEMORY.md
#   FAKE_HERMES_SLEEP           hang this many seconds (timeout tests)
set -u

if [ -n "${FAKE_HERMES_LOG:-}" ]; then
  { printf '%s\037' "$@"; printf '\036'; } >> "$FAKE_HERMES_LOG"
fi

if [ "${1:-}" = "--version" ]; then
  echo "Hermes Agent v0.23.2 (2026.9.24)"
  exit 0
fi

: "${HERMES_HOME:?HERMES_HOME must be set}"

if [ "${1:-}" = "profile" ]; then
  dir="$HERMES_HOME/profiles/$3"
  case "$2" in
    create)
      if [ -e "$dir" ]; then echo "Error: profile '$3' already exists" >&2; exit 1; fi
      mkdir -p "$dir/memories" "$dir/sessions" "$dir/home"
      exit 0;;
    delete)
      rm -rf "$dir"
      exit 0;;
  esac
  exit 2
fi

profile="" usage=""
while [ $# -gt 0 ]; do
  case "$1" in
    -p) profile=$2; shift 2;;
    -z) shift 2;;
    --usage-file) usage=$2; shift 2;;
    -m|-t|--provider) shift 2;;
    *) echo "fake hermes: unknown argument $1" >&2; exit 2;;
  esac
done

dir="$HERMES_HOME/profiles/$profile"
if [ -z "$profile" ] || [ ! -d "$dir" ]; then
  echo "Error: Profile '$profile' does not exist." >&2
  exit 1
fi

if [ -n "${FAKE_HERMES_SLEEP:-}" ]; then
  exec sleep "$FAKE_HERMES_SLEEP"
fi

mem="$dir/memories/MEMORY.md"
if [ -n "${FAKE_HERMES_PATCH_OLD:-}" ] && [ -f "$mem" ]; then
  content=$(cat "$mem")
  old=$FAKE_HERMES_PATCH_OLD new=${FAKE_HERMES_PATCH_NEW:-}
  printf '%s' "${content//"$old"/$new}" > "$mem"
fi
if [ -n "${FAKE_HERMES_MEMORY_ADD:-}" ]; then
  if [ -s "$mem" ]; then printf '\n\302\247\n%s' "$FAKE_HERMES_MEMORY_ADD" >> "$mem"
  else printf '%s' "$FAKE_HERMES_MEMORY_ADD" > "$mem"; fi
fi

if [ -n "$usage" ] && [ -z "${FAKE_HERMES_NO_USAGE:-}" ]; then
  if [ -n "${FAKE_HERMES_USAGE_JSON:-}" ]; then
    printf '%s\n' "$FAKE_HERMES_USAGE_JSON" > "$usage"
  else
    in=${FAKE_HERMES_INPUT_TOKENS:-1000} out=${FAKE_HERMES_OUTPUT_TOKENS:-200} aux=${FAKE_HERMES_AUX_TOKENS:-50}
    printf '{"input_tokens": %d, "output_tokens": %d, "total_tokens": %d, "api_calls": 1, "cost": 0, "total_including_auxiliary": {"total_tokens": %d, "api_calls": 2}}\n' \
      "$in" "$out" $((in + out)) $((in + out + aux)) > "$usage"
  fi
fi

code=${FAKE_HERMES_EXIT:-0}
if [ "$code" != 1 ]; then
  printf '%s\n' "${FAKE_HERMES_OUTPUT-Hello from the fake hermes.}"
fi
exit "$code"
