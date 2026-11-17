"""Importing this package registers every method with the registry; import it before `load_config`/`build`."""

from agent_memory.methods import full_context, naive_rag, write_filter, write_raw  # noqa: F401
from agent_memory.methods.full_context import stage  # noqa: F401
from agent_memory.methods.write_filter import stage as _write_filter  # noqa: F401
from agent_memory.methods.write_raw import stage as _write_raw  # noqa: F401
from agent_memory.methods import coala_stores, pool_route  # noqa: F401
from agent_memory.methods.coala_stores import stage as _coala_stores  # noqa: F401
from agent_memory.methods.pool_route import stage as _pool_route  # noqa: F401
from agent_memory.methods import rules_only, tag_recall  # noqa: F401
from agent_memory.methods.rules_only import stage as _rules_only  # noqa: F401
from agent_memory.methods.tag_recall import stage as _tag_recall  # noqa: F401
from agent_memory.methods import scored_recall  # noqa: F401
from agent_memory.methods.scored_recall import stage as _scored_recall  # noqa: F401
from agent_memory.methods import reflect  # noqa: F401
from agent_memory.methods.reflect import stage as _reflect  # noqa: F401
from agent_memory.methods import overwrite  # noqa: F401
from agent_memory.methods.overwrite import stage as _overwrite  # noqa: F401
from agent_memory.methods import expire  # noqa: F401
from agent_memory.methods.expire import stage as _expire  # noqa: F401
from agent_memory.methods import archive  # noqa: F401
from agent_memory.methods.archive import stage as _archive  # noqa: F401
from agent_memory.methods import reflexion  # noqa: F401
from agent_memory.methods.reflexion import stage as _reflexion  # noqa: F401
