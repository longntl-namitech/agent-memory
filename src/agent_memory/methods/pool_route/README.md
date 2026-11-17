# pool_route

Sort stage, the default when a config has no `[sort]`. A route: callable object `PoolRoute()(store, task) -> Routed`, a pure function of store and task (no clock).

All active entries of every kind are treated as one pool and returned in `Routed.facts` (rules, then facts, then log lines, each in store order); `Routed.rules` and `Routed.log` are empty. Kind and tags are ignored. Archived entries are never routed.

Constants: none.
