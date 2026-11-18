# Chat demo: pitch checklist

The demo must be run from a checkout of the repo: the demo configs (`configs/demo/`) and the default `.demo/` folder are not packaged in a wheel. It is a local web page with two assistants answering the same messages side by side: one with no memory and one with the lab's full memory (write, sort, recall, reflect, forget). It is a toy personal assistant for a fictional user named An, not part of the lab's measurements. See the [Demo section of the README](../README.md#demo) for the short version.

## Before the pitch

0. Do the warm-up in advance, not on stage: it calls the model, costs tokens and takes time.
1. Set the environment (read on the server, never sent to the page):
   - Required for live mode and `--warmup`: `OPENAI_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`.
   - Optional: `OPENAI_BASE_URL`, `OPENAI_MODEL` (default `gpt-5.4-nano`), `EMBEDDING_API_KEY`.
   - Replay mode needs none of them, but it needs the data folder of a finished warm-up: the warm-up saves the model names (names only, no keys) in `llm-cache-rehearsed/meta.json` and replay uses those. `--mode replay` without a warm-up exits with an error.
2. Look at the estimate (no network call):

   ```bash
   uv run agent-memory demo --estimate-only
   ```

   It prints the estimated tokens and the data folder. The estimate is a placeholder: 3,000 tokens per scripted turn, 4 turns (three prompts plus the second act), so 12,000. It is unverified until a real warm-up has been measured.
3. Run the warm-up once. It calls the model for real and costs tokens, so get the owner's go-ahead first:

   ```bash
   uv run agent-memory demo --warmup
   ```

   It runs the three prompts and the second-act prompt live, stores the answers in `.demo/llm-cache-rehearsed/`, and prints the tokens used. Replay serves from that cache, so it only works for those exact messages, sent from a fresh start in the same order (the three prompts, then the second act), with no "Advance a day", "Run Friday reflect" or forgotten entries in between.
4. Start the demo and open the printed address (`http://127.0.0.1:8765/` by default):

   ```bash
   uv run agent-memory demo              # live mode (default)
   uv run agent-memory demo --mode replay  # offline, from the warm-up cache
   ```

   Flags: `--port` (default 8765), `--max-tokens` (cap per column, default 100,000), `--mode live|replay`, `--data-dir`. The server listens on 127.0.0.1 only and refuses requests with another `Host` or a cross-site `Origin`.

## The story

Use the three example prompts above the input (or type them):

1. `I'm An, I live in Ho Chi Minh City. Remind me to call the dentist on Friday.` The memory column keeps the name and city as facts, adds a to-do and a log line. The other column replies and keeps nothing.
2. `I just moved to Hanoi.` The `city` fact is overwritten and the old value is shown as replaced.
3. `Where do I live and what's on my list?` The memory column answers from memory (open "What the assistant saw" to show why); the other column says it does not know.

Optional second act: send `This week I'm on a diet.`, then press "Advance a day" seven times. The LOG lines expire and are archived after seven days while the facts and the to-do list stay. "Run Friday reflect" makes one model call (it is not in the warm-up cache, so in replay that column shows the miss message) that reads the active log lines and may write up to 3 rules from them, archiving the log lines it used.

Each memory entry has a button to forget it. "Reset" returns both columns to the start (date back to Monday 2026-01-05).

## Live, replay and failover

- Live always calls the model, so the token meter moves on every answer. Each column has its own cap, and spent tokens stay counted until the process restarts: "Reset", "Wipe all data" and mode switches do not zero them; a column that reaches it shows "Token cap reached" and the other keeps going.
- Replay never calls the model. Changing what the memory holds (advancing the date, forgetting an entry, reflecting) changes the next prompts, so later turns can miss. A message that is not in the warm-up cache shows "Not in the rehearsed script, replay cannot answer" in that column.
- If a live call fails (network or provider error), the demo switches to replay by itself and says so: "Live call failed, switched to replay. Memory rebuilt from your N messages. The date, reflect and forgotten items were reset." Only your messages are replayed: both columns are reset first, the date goes back to the start and "Run Friday reflect" and forgotten entries are not redone. Messages you typed freely show the miss message.
- Live calls time out after 20 seconds (one retry), which also counts as a failure. The "Replay" button does the same switch by hand, with the notice "Switched to replay. Memory rebuilt from your N messages. The date, reflect and forgotten items were reset."; "Live" switches back and keeps the token counts.

## If something goes wrong

- Live call failing on stage: let the automatic switch happen, or press "Replay" before it fails; then use the three example prompts.
- Replay says "Not in the rehearsed script": use the example prompts, or run the warm-up again (the model or the data folder may have changed).
- Token cap reached: restart with a higher `--max-tokens`, or switch to replay.
- Start over: "Reset" for the memory, "Wipe all data" for everything. Wiping deletes only the demo's own folders in the data folder (`stores/`, both LLM caches, `embedding-cache/`), including the warm-up cache, so run `--warmup` again before the next replay.

## Privacy and data

- Text typed into the demo is sent to the configured LLM and embedding providers in live mode and in the warm-up. Do not type anything you do not want a provider to see.
- The page makes no request to any host except the local server, and the key is never sent to the page or logged.
- All stored data lives in `.demo/` (gitignored): `stores/`, `llm-cache-live/`, `llm-cache-rehearsed/`, `embedding-cache/` (the LLM caches have one subfolder per column). The default is the repo's `.demo/` folder and `--data-dir` changes the location; the "Wipe all data" button asks for a second click to confirm.

## Page basics

The page starts dark (the system colour scheme is not used); "Light theme" switches and the choice is remembered in the browser. Enter sends the message. The memory tabs (RULES, FACTS, LOG) work with the arrow keys, Home and End; Escape closes the "What the assistant saw" panel and the notice banner.
