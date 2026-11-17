"""Importing this package registers every method with the registry; import it before `load_config`/`build`."""

from agent_memory.methods import full_context, naive_rag  # noqa: F401
