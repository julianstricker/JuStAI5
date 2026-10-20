"""Builtin core tools (always available, independent of plugins)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from justai.container import Container


def register_builtin_tools(c: Container) -> None:
    from justai.tools.builtin import control, conversation, system

    system.register(c)
    conversation.register(c)
    control.register(c)
    for ext in c.extensions.values():
        register = getattr(ext, "register_tools", None)
        if register is not None:
            register(c.tools)
