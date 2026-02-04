import json
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class GuardError(ValueError):
    pass


class TimeoutError(RuntimeError):
    pass


@dataclass
class StepRecord:
    name: str
    status: str
    duration_ms: int
    attempts: int
    error: Optional[str] = None


@dataclass
class ExecutionReport:
    meta: Dict[str, Any] = field(default_factory=dict)
    steps: List[StepRecord] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    result: Any = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def finish(self, result: Any) -> None:
        self.result = result
        self.finished_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        duration_ms = None
        if self.finished_at is not None:
            duration_ms = int((self.finished_at - self.started_at) * 1000)
        return {
            "meta": self.meta,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": duration_ms,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "duration_ms": s.duration_ms,
                    "attempts": s.attempts,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "events": self.events,
            "result": self.result,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


_CURRENT_REPORT: Optional[ExecutionReport] = None


def _set_current_report(report: ExecutionReport) -> None:
    global _CURRENT_REPORT
    _CURRENT_REPORT = report


def _clear_current_report() -> None:
    global _CURRENT_REPORT
    _CURRENT_REPORT = None


def log_event(kind: str, **fields: Any) -> None:
    if _CURRENT_REPORT is None:
        return
    event = {
        "kind": kind,
        "ts": time.time(),
    }
    event.update(fields)
    _CURRENT_REPORT.events.append(event)


class _TimeLimit:
    def __init__(self, seconds: Optional[int]) -> None:
        self.seconds = seconds
        self._prev = None

    def _handle(self, _signum, _frame) -> None:
        raise TimeoutError(f"Step exceeded timeout of {self.seconds}s")

    def __enter__(self):
        if not self.seconds:
            return self
        try:
            self._prev = signal.signal(signal.SIGALRM, self._handle)
            signal.setitimer(signal.ITIMER_REAL, self.seconds)
        except Exception:
            # If signals aren't available, skip hard timeout.
            self._prev = None
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        if not self.seconds:
            return False
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
            if self._prev is not None:
                signal.signal(signal.SIGALRM, self._prev)
        except Exception:
            pass
        return False


def step(
    *,
    retry: int = 0,
    timeout: Optional[int] = None,
    guard: Optional[List[str]] = None,
    produces: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    guard = guard or []

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args, **kwargs):
            attempts = max(1, 1 + int(retry))
            last_err: Optional[Exception] = None
            for attempt in range(1, attempts + 1):
                log_event("step_start", step=fn.__name__, attempt=attempt)
                started = time.perf_counter()
                try:
                    with _TimeLimit(timeout):
                        result = fn(*args, **kwargs)
                    if guard and isinstance(result, str):
                        for token in guard:
                            if token in result:
                                raise GuardError(f"Guard token detected: {token}")
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    if _CURRENT_REPORT is not None:
                        _CURRENT_REPORT.steps.append(
                            StepRecord(
                                name=fn.__name__,
                                status="ok",
                                duration_ms=duration_ms,
                                attempts=attempt,
                            )
                        )
                    log_event(
                        "step_end",
                        step=fn.__name__,
                        attempt=attempt,
                        status="ok",
                        duration_ms=duration_ms,
                    )
                    return result
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    if _CURRENT_REPORT is not None:
                        _CURRENT_REPORT.steps.append(
                            StepRecord(
                                name=fn.__name__,
                                status="error",
                                duration_ms=duration_ms,
                                attempts=attempt,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        )
                    log_event(
                        "step_end",
                        step=fn.__name__,
                        attempt=attempt,
                        status="error",
                        duration_ms=duration_ms,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    if attempt == attempts:
                        raise
            if last_err is not None:
                raise last_err
            return None

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__module__ = fn.__module__
        wrapper.__vibelang__ = {
            "retry": retry,
            "timeout": timeout,
            "guard": guard,
            "produces": produces,
        }
        return wrapper

    return decorator
