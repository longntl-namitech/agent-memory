"""Name -> factory registry for stages, whole memories and whole agents.

Kinds: write, sort, recall, reflect, retry, forget, memory, agent.
"""

from typing import Any, Callable

_REGISTRY: dict[tuple[str, str], Callable[..., Any]] = {}


class ConfigError(ValueError):
    pass


def register(name: str, kind: str):
    def deco(factory):
        _REGISTRY[(kind, name)] = factory
        return factory

    return deco


def has(name: str, kinds: tuple[str, ...]) -> bool:
    return any((k, name) in _REGISTRY for k in kinds)


def lookup(name: str, kinds: tuple[str, ...]) -> tuple[str, Callable[..., Any]]:
    for k in kinds:
        if (k, name) in _REGISTRY:
            return k, _REGISTRY[(k, name)]
    raise ConfigError(f"unknown {'/'.join(kinds)} stage: {name!r}")
