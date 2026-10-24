import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol, Tuple


class Hardware(Protocol):
    def cpu_temperature(self) -> Optional[float]: ...
    def memory(self) -> Tuple[float, float]: ...
    async def game_running(self) -> bool: ...


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_timeout_seconds: int = 300
    logger: Any = field(default_factory=lambda: logging.getLogger("admission"), repr=False)

    failure_count: int = field(default=0, init=False)
    last_failure_time: Optional[datetime] = field(default=None, init=False)
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:

            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.reset_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.logger.info("Circuit breaker entering half-open state")
                    return True
            return False


        return True

    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.logger.debug("Circuit breaker: success recorded, state=CLOSED")

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:

            self.state = CircuitState.OPEN
            self.logger.warning("Circuit breaker opened after half-open failure")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def get_status(self) -> Dict:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


@dataclass
class RateLimiter:
    cooldown_seconds: int = 20
    logger: Any = field(default_factory=lambda: logging.getLogger("admission"), repr=False)

    last_request_time: Optional[datetime] = field(default=None, init=False)

    def can_request(self) -> Tuple[bool, str]:
        now = datetime.now()


        if self.last_request_time:
            elapsed = (now - self.last_request_time).total_seconds()
            if elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                return False, f"Cooldown active: {remaining:.0f}s remaining"

        return True, "OK"

    def record_request(self):
        self.last_request_time = datetime.now()
        self.logger.info("Rate limiter: request recorded")

    def update_cooldown(self, cooldown_seconds: int):
        self.cooldown_seconds = cooldown_seconds
        self.logger.info(f"Rate limiter: cooldown updated to {cooldown_seconds}s")

    def get_status(self) -> Dict:
        can_request, reason = self.can_request()
        cooldown_remaining = 0

        if self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            cooldown_remaining = max(0, self.cooldown_seconds - elapsed)

        return {
            "cooldown_remaining_seconds": cooldown_remaining,
            "can_request": can_request,
            "reason": reason
        }


class ResourceMonitor:
    min_memory_mb: int = 800

    def __init__(self, hardware: Hardware, enabled: bool = True, max_temp_celsius: int = 80,
                 logger: Optional[logging.Logger] = None):
        self.hardware = hardware
        self.enabled = enabled
        self.max_temp_celsius = max_temp_celsius
        self._log = logger or logging.getLogger("admission")
        if not enabled:
            self._log.warning("ResourceMonitor: Resource monitoring DISABLED - checks will always pass")

    def check_resources(self) -> Tuple[bool, str]:
        if not self.enabled:
            return True, "Resource monitoring disabled"

        try:
            available_mb, _ = self.hardware.memory()
            if available_mb < self.min_memory_mb:
                return False, f"Insufficient memory: {available_mb:.0f}MB available, {self.min_memory_mb}MB required"
        except Exception as e:


            self._log.warning(f"Memory check failed, blocking LLM: {e}")
            return False, "Resource check unavailable"

        try:
            temp = self.hardware.cpu_temperature()
            if temp and temp > self.max_temp_celsius:
                return False, f"CPU too hot: {temp}°C (max {self.max_temp_celsius}°C)"
        except Exception as e:
            self._log.debug(f"Temperature check failed: {e}")


        return True, "Resources OK"

    def get_status(self) -> Dict:
        if not self.enabled:
            return {
                "enabled": False,
                "memory_available_mb": None,
                "memory_percent_used": None,
                "cpu_temp_celsius": None,
                "can_proceed": True,
                "message": "Resource monitoring disabled"
            }

        try:
            available_mb, percent_used = self.hardware.memory()
            return {
                "enabled": True,
                "memory_available_mb": available_mb,
                "memory_percent_used": percent_used,
                "cpu_temp_celsius": self.hardware.cpu_temperature(),
                "can_proceed": self.check_resources()[0]
            }
        except Exception as e:
            self._log.warning(f"Resource status check failed: {e}")
            return {
                "enabled": True,
                "memory_available_mb": None,
                "memory_percent_used": None,
                "cpu_temp_celsius": None,
                "can_proceed": True,
                "error": str(e)
            }


@dataclass
class Plan:
    max_tokens: int
    n_threads: int


class Admission:
    def __init__(
        self,
        hardware: Hardware,
        *,
        resource_monitoring_enabled: bool = True,
        temp_ceiling: int = 75,
        cooldown_seconds: int = 20,
        thermal_bonus_seconds: int = 30,
        adaptive_tokens: bool = True,
        reduced_token_count: int = 80,
        adaptive_threads: bool = True,
        default_threads: int = 2,
        clock: Callable[[], float] = time.time,
        logger: Optional[logging.Logger] = None,
    ):
        self._log = logger or logging.getLogger("admission")
        self.hardware = hardware
        self.circuit_breaker = CircuitBreaker(logger=self._log)
        self.rate_limiter = RateLimiter(cooldown_seconds=cooldown_seconds, logger=self._log)
        self.resource_monitor = ResourceMonitor(
            hardware, enabled=resource_monitoring_enabled, max_temp_celsius=temp_ceiling, logger=self._log
        )
        self.thermal_bonus_seconds = thermal_bonus_seconds
        self.adaptive_tokens = adaptive_tokens
        self.reduced_token_count = reduced_token_count
        self.adaptive_threads = adaptive_threads
        self.default_threads = default_threads
        self.thermal_bonus_until: Optional[float] = None
        self._clock = clock

    async def check(self, allow_during_gaming: bool = False) -> Optional[str]:
        if not self.circuit_breaker.can_execute():
            return "Service temporarily unavailable (circuit breaker open)"

        now = self._clock()
        if self.thermal_bonus_until is not None and now < self.thermal_bonus_until:
            remaining = self.thermal_bonus_until - now
            self._log.info(f"[LLM] Thermal bonus active: {remaining:.0f}s remaining")
            return f"Thermal recovery in progress: {remaining:.0f}s remaining"

        can_request, reason = self.rate_limiter.can_request()
        if not can_request:
            return reason

        can_proceed, reason = self.resource_monitor.check_resources()
        if not can_proceed:
            return reason

        if await self.hardware.game_running() and not allow_during_gaming:
            return "Summarization blocked: game is running"
        return None

    def _soft_threshold(self) -> float:
        return self.resource_monitor.max_temp_celsius - 5

    async def plan(self, max_gen_tokens: int) -> Plan:
        temp = self.hardware.cpu_temperature()
        hot = temp is not None and temp > self._soft_threshold()

        if self.adaptive_tokens and hot:
            max_tokens = self.reduced_token_count
            self._log.info(f"[LLM] Adaptive tokens: {temp:.1f}°C > {self._soft_threshold()}°C, using {max_tokens} tokens")
        else:
            max_tokens = max_gen_tokens

        if not self.adaptive_threads:
            return Plan(max_tokens, self.default_threads)
        n_threads = 1 if hot or await self.hardware.game_running() else 2
        self._log.info(f"[LLM] Adaptive threads: {n_threads} (hot={hot})")
        return Plan(max_tokens, n_threads)

    def record_success(self) -> None:
        self.circuit_breaker.record_success()
        self.rate_limiter.record_request()

        temp = self.hardware.cpu_temperature()
        if temp is not None and temp > self._soft_threshold() and self.thermal_bonus_seconds > 0:
            self.thermal_bonus_until = self._clock() + self.thermal_bonus_seconds
            self._log.info(f"[LLM] Thermal bonus set: {temp:.1f}°C, bonus={self.thermal_bonus_seconds}s")

    def record_failure(self) -> None:
        self.circuit_breaker.record_failure()

    def status(self) -> Dict:
        return {
            "circuit_breaker": self.circuit_breaker.get_status(),
            "rate_limiter": self.rate_limiter.get_status(),
            "resources": self.resource_monitor.get_status(),
        }
