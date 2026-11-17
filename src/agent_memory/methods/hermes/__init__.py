"""Hermes Agent whole-agent baseline; importing it registers the `hermes` agent."""

import os
from pathlib import Path

from agent_memory.core.registry import register
from agent_memory.methods.hermes.adapter import HermesAgent, HermesError, MemoryMdStore

__all__ = ["HermesAgent", "HermesError", "MemoryMdStore", "make_hermes"]


@register("hermes", "agent")
def make_hermes(config, llm, store, **deps) -> HermesAgent:
    """Options come from the config's [hermes] table; `deps` override them (tests pass a fake binary and home).
    `store` is unused: Hermes keeps its own MEMORY.md, exposed as `agent.store`. The token cap is `llm.budget`."""
    opts = {**config.options.get("hermes", {}), **deps}
    return HermesAgent(Path(opts.get("profile_root", f".hermes-lab/{config.name}")), opts.get("model", "gpt-5.4-nano"),
                       bool(opts.get("memory_enabled", True)), opts.get("binary", "hermes"),
                       base_url=opts.get("base_url") or os.environ.get("OPENAI_BASE_URL"),
                       key_env=opts.get("key_env"), max_turns=opts.get("max_turns", 20),
                       timeout=opts.get("timeout", 600), budget=llm.budget if llm is not None else None,
                       env=opts.get("env"), install_home=Path(opts.get("install_home", ".hermes-home")))
