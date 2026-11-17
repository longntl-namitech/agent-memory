"""TOML config -> Config -> Agent. Shape per spec "Configs"; stand-ins per plan A1."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from agent_memory.core import registry
from agent_memory.core.layout import Store
from agent_memory.core.llm import LLMClient
from agent_memory.core.memory import Agent, Check, MemoryAgent, StagedMemory
from agent_memory.core.registry import ConfigError

__all__ = ["Config", "ConfigError", "build", "load_config"]

# section -> registry kinds a name there may have; the A1 stand-ins are the Config defaults
_SINGLE = {"write": ("write",), "sort": ("sort",), "recall": ("recall",)}
_MULTI = {"reflect": ("reflect", "retry"), "forget": ("forget",)}  # reflexion registers as kind "retry"


@dataclass
class Config:
    name: str = ""
    agent: str | None = None  # a whole agent, e.g. "hermes"
    memory: str | None = None  # a whole memory, e.g. "naive_rag"
    write: str = "write_raw"
    sort: str = "pool_route"
    recall: str = "rules_only"
    reflect: list[str] = field(default_factory=list)
    forget: list[str] = field(default_factory=list)
    options: dict = field(default_factory=dict)  # any other table, e.g. [hermes]


def _check(name, kinds: tuple[str, ...]) -> str:
    if not isinstance(name, str) or not registry.has(name, kinds):
        raise ConfigError(f"unknown {'/'.join(kinds)} stage: {name!r}")
    return name


def load_config(path: Path) -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    cfg = Config(name=raw.pop("name", Path(path).stem))
    if "agent" in raw:
        cfg.agent = _check(raw.pop("agent"), ("agent",))
    if "memory" in raw:
        cfg.memory = _check(raw.pop("memory"), ("memory",))
    # Names written in the file are checked now; absent sections keep their stand-in, checked at build.
    for sec, kinds in _SINGLE.items():
        if sec in raw:
            setattr(cfg, sec, _check(raw.pop(sec).get("stage"), kinds))
    for sec, kinds in _MULTI.items():
        if sec in raw:
            setattr(cfg, sec, [_check(n, kinds) for n in raw.pop(sec).get("stages", [])])
    for key, val in raw.items():
        if not isinstance(val, dict):
            raise ConfigError(f"unknown config key: {key!r}")
        cfg.options[key] = val
    return cfg


def build(config: Config, *, llm: LLMClient, store: Store, check: Check | None = None, **deps) -> Agent:
    """Whole agents get (config, llm, store, **deps); whole memories get (store, llm, **deps); stages take no args."""
    if config.agent:
        return registry.lookup(config.agent, ("agent",))[1](config=config, llm=llm, store=store, **deps)
    if config.memory:
        memory = registry.lookup(config.memory, ("memory",))[1](store=store, llm=llm, **deps)
        return MemoryAgent(memory, llm, check=check)
    one = {sec: registry.lookup(getattr(config, sec), kinds)[1]() for sec, kinds in _SINGLE.items()}
    reflectors, retries = [], []
    for name in config.reflect:
        kind, factory = registry.lookup(name, _MULTI["reflect"])
        (retries if kind == "retry" else reflectors).append(factory())
    forgetters = [registry.lookup(n, _MULTI["forget"])[1]() for n in config.forget]
    memory = StagedMemory(store, llm, one["write"], one["sort"], one["recall"], reflectors, forgetters)
    return MemoryAgent(memory, llm, retries, check)
