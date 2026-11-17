# coala_stores

Sort stage. A route: callable object `CoalaStores()(store, task) -> Routed(rules, facts, log)`, a pure function of store and task (no clock).

- RULES: all active rules, always.
- FACTS: active facts whose tags intersect `task.tags`, plus facts tagged `global`; de-duplicated by id, ordered by task tag then store order.
- LOG: all active log lines only when `task.wants_log` is true, otherwise empty.
- Archived entries are never routed.

Constants: `GLOBAL_TAG = "global"`.
