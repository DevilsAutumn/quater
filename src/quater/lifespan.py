"""Application lifespan hook management."""

from __future__ import annotations

from enum import StrEnum

from quater.exceptions import LifespanStateError
from quater.typing import LifespanHook


class LifespanState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class LifespanManager:
    """Registers and runs app startup/shutdown hooks."""

    __slots__ = ("_shutdown_hooks", "_startup_hooks", "_state")

    def __init__(self) -> None:
        self._startup_hooks: list[LifespanHook] = []
        self._shutdown_hooks: list[LifespanHook] = []
        self._state = LifespanState.IDLE

    @property
    def state(self) -> LifespanState:
        return self._state

    @property
    def has_hooks(self) -> bool:
        return bool(self._startup_hooks or self._shutdown_hooks)

    def on_startup(self, hook: LifespanHook) -> LifespanHook:
        self._ensure_mutable()
        self._startup_hooks.append(hook)
        return hook

    def on_shutdown(self, hook: LifespanHook) -> LifespanHook:
        self._ensure_mutable()
        self._shutdown_hooks.append(hook)
        return hook

    async def startup(self) -> None:
        if self._state is LifespanState.STARTED:
            return
        if self._state is LifespanState.FAILED:
            raise LifespanStateError("Cannot start an app after startup failed")
        if self._state in {LifespanState.STARTING, LifespanState.STOPPING}:
            raise LifespanStateError(
                f"Cannot start app while lifespan is {self._state}"
            )

        self._state = LifespanState.STARTING
        try:
            for hook in self._startup_hooks:
                await hook()
        except BaseException:
            self._state = LifespanState.FAILED
            raise
        self._state = LifespanState.STARTED

    async def shutdown(self) -> None:
        if self._state in {LifespanState.IDLE, LifespanState.STOPPED}:
            return
        if self._state is LifespanState.FAILED:
            return
        if self._state is not LifespanState.STARTED:
            raise LifespanStateError(
                f"Cannot shutdown app while lifespan is {self._state}"
            )

        self._state = LifespanState.STOPPING
        try:
            for hook in reversed(self._shutdown_hooks):
                await hook()
        except BaseException:
            self._state = LifespanState.FAILED
            raise
        self._state = LifespanState.STOPPED

    def _ensure_mutable(self) -> None:
        if self._state is not LifespanState.IDLE:
            raise LifespanStateError(
                "Cannot register lifespan hooks after startup begins"
            )
