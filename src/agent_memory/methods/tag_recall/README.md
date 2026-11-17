# tag_recall

Recall stage. `TagRecall().recall(task, store, now, route) -> str`. Calls `route(store, task)` and renders the result; it does no selection of its own, so the sort stage decides what reaches the prompt (with `pool_route` everything does, each entry still rendered by its own kind).

Simulation-only: the tags it relies on come from the task (company slug plus `global`), which LongMemEval does not have.

Format (text only, no ids or timestamps; empty sections omitted; store order kept):

```
## RULES
<rule text>

## FACTS
<key>: <fact text>

## LOG
<log text>
```

Every rendered entry gets `last_used_at = now` via `Store.touch`. Constants: none.
