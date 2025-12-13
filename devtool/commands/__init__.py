from __future__ import annotations

from typing import Callable, Dict

CONFIGURATORS: Dict[str, Callable] = {}


def register(name: str):
    def deco(configure: Callable):
        CONFIGURATORS[name] = configure
        return configure

    return deco
