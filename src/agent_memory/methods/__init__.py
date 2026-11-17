"""Importing this package registers every method with the registry; import it before `load_config`/`build`."""

from agent_memory.methods import full_context, naive_rag, write_filter, write_raw  # noqa: F401
from agent_memory.methods.full_context import stage  # noqa: F401
from agent_memory.methods.write_filter import stage as _write_filter  # noqa: F401
from agent_memory.methods.write_raw import stage as _write_raw  # noqa: F401
