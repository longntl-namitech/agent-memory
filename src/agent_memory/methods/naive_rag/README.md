# naive_rag

Baseline whole memory. `write` embeds the event text (one embedder call) and stores it as a LOG entry.
`recall` embeds "name company product" from the task's lead and returns the top-k past events by cosine
similarity, one per line. No rules, facts or tags. `reflect` and `forget` do nothing.

Constants: `TOP_K = 5`. Needs an `embedder` dependency.
