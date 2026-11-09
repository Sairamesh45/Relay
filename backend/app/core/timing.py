"""Request timing context and Server-Timing header generation.

Provides high-resolution phase latency tracking without logging secrets,
tokens, or sensitive parameters.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar

current_timing_context: ContextVar[RequestTimingContext | None] = ContextVar(
    "current_timing_context", default=None
)


def get_current_timing_context() -> RequestTimingContext | None:
    """Return the active request timing context if currently in an instrumented request."""
    return current_timing_context.get()


class RequestTimingContext:
    """Tracks latency metrics across discrete request execution phases."""

    STANDARD_PHASES: tuple[str, ...] = ("auth", "db", "proc", "total")

    def __init__(self) -> None:
        self.durations: dict[str, float] = {
            "auth": 0.0,
            "db": 0.0,
            "proc": 0.0,
            "total": 0.0,
        }

    @asynccontextmanager
    async def measure(self, phase: str) -> AsyncGenerator[None, None]:
        """Measure elapsed execution time of an asynchronous code block in milliseconds."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            self.durations[phase] = self.durations.get(phase, 0.0) + elapsed_ms

    def record(self, phase: str, duration_ms: float) -> None:
        """Manually record a phase duration in milliseconds."""
        self.durations[phase] = self.durations.get(phase, 0.0) + round(duration_ms, 2)

    def format_server_timing_header(self) -> str:
        """Format recorded phase latencies as a W3C Server-Timing header value.

        Emits strictly numeric metrics (e.g. 'auth;dur=1.4, db;dur=8.2, proc;dur=4.1, total;dur=15.8')
        with zero sensitive data leakage.
        """
        ordered_keys: list[str] = [
            p for p in self.STANDARD_PHASES if p in self.durations
        ]
        for key in self.durations:
            if key not in ordered_keys:
                ordered_keys.append(key)

        parts = [f"{phase};dur={self.durations[phase]:.1f}" for phase in ordered_keys]
        return ", ".join(parts)
