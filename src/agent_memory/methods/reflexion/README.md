# reflexion

Retry stage. After a failed check, `MemoryAgent` calls `Reflexion.retry` once. One LLM call (`purpose="reflexion"`) is told the name of the failed check (for example `vat` or `booking_link`), the lead, the first output and the recalled context. It replies with JSON `{"note": ..., "output": ...}`: a short reflection (what went wrong, what to do next time) and the corrected output.

- The output replaces the first one. The note goes through `memory.write` as a `reflection` event, so the configured write stage stores (or drops) it. An empty note is not written.
- Configured as `[reflect] stages = ["reflect", "reflexion"]`.
- Invalid JSON or an empty output: the raw reply is the output, the note is empty, there is no second call, and the instance attribute `fallbacks` is incremented.

**The check acts as an oracle.** The retry only happens because a rule-based check told the agent exactly which rule failed, as in the Reflexion paper where the environment gives the feedback. This makes `reflexion` stronger than a real deployment, where no such oracle exists.

Constants: one retry per task (a second failing check is not retried, and `AgentResult.failed_check` still reports it); no retry when the check passes. It does not run on LongMemEval, which has no check.
