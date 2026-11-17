# full_context

Baseline whole memory. `write` appends every event, unfiltered, as one LOG entry. `recall` returns the whole
history (active entries, oldest first), one event per line. `reflect` and `forget` do nothing.

Constants: none. It will outgrow the context window on long runs - that is the point of the baseline.
