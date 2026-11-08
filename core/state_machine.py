"""
AUREUS-SMC Institutional State Machine
Manages deterministic lifecycle states and state transitions for the algorithmic engine.
"""

from __future__ import annotations
import logging
from typing import Set, Dict, Optional
from core.models import SystemState
from core.events import SystemStateChangedEvent
from core.event_bus import event_bus

logger = logging.getLogger("StateMachine")


class TradingStateMachine:
    """
    Deterministic State Machine enforcing institutional execution rules:
    - No trading outside NY Open execution window
    - Strict progression: Sweep -> Displacement (MSS) -> FVG formation -> Order -> In Position
    - Circuit Breaker locks system until reset
    """

    # Allowed state transitions
    TRANSITIONS: Dict[SystemState, Set[SystemState]] = {
        SystemState.INIT: {SystemState.IDLE, SystemState.LONDON_ACCUMULATION, SystemState.NY_SCANNING_SWEEP, SystemState.CIRCUIT_BREAKER},
        SystemState.IDLE: {SystemState.LONDON_ACCUMULATION, SystemState.NY_SCANNING_SWEEP, SystemState.CIRCUIT_BREAKER},
        SystemState.LONDON_ACCUMULATION: {SystemState.NY_SCANNING_SWEEP, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.NY_SCANNING_SWEEP: {SystemState.NY_SCANNING_DISPLACEMENT, SystemState.IDLE, SystemState.CIRCUIT_BREAKER, SystemState.COOLDOWN},
        SystemState.NY_SCANNING_DISPLACEMENT: {SystemState.NY_SCANNING_FVG, SystemState.NY_SCANNING_SWEEP, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.NY_SCANNING_FVG: {SystemState.PENDING_ORDER, SystemState.NY_SCANNING_SWEEP, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.PENDING_ORDER: {SystemState.IN_POSITION, SystemState.NY_SCANNING_SWEEP, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.IN_POSITION: {SystemState.COOLDOWN, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.COOLDOWN: {SystemState.NY_SCANNING_SWEEP, SystemState.IDLE, SystemState.CIRCUIT_BREAKER},
        SystemState.CIRCUIT_BREAKER: {SystemState.IDLE}  # Can only be manually reset or at session start next day
    }

    def __init__(self, initial_state: SystemState = SystemState.INIT) -> None:
        self._current_state: SystemState = initial_state
        self._previous_state: Optional[SystemState] = None
        self._reason: str = "Initial system startup"

    @property
    def state(self) -> SystemState:
        return self._current_state

    @property
    def previous_state(self) -> Optional[SystemState]:
        return self._previous_state

    async def transition_to(self, new_state: SystemState, reason: str = "") -> bool:
        """
        Attempts a transition to the new state. Returns True if successful, False if invalid.
        Dispatches SystemStateChangedEvent upon success.
        """
        if new_state == self._current_state:
            return True

        allowed = self.TRANSITIONS.get(self._current_state, set())
        # Circuit Breaker can always be triggered as a fail-safe
        if new_state != SystemState.CIRCUIT_BREAKER and new_state not in allowed:
            logger.warning(
                f"Invalid state transition attempted: {self._current_state.value} -> {new_state.value}. Denied."
            )
            return False

        self._previous_state = self._current_state
        self._current_state = new_state
        self._reason = reason

        logger.info(f"STATE CHANGE: [{self._previous_state.value}] -> [{new_state.value}] | Reason: {reason}")

        event = SystemStateChangedEvent(
            previous_state=self._previous_state,
            new_state=self._current_state,
            reason=reason
        )
        await event_bus.publish(event)
        return True

    def can_enter_trades(self) -> bool:
        """Helper to check if trading entries are permitted in the current state."""
        return self._current_state in {
            SystemState.NY_SCANNING_SWEEP,
            SystemState.NY_SCANNING_DISPLACEMENT,
            SystemState.NY_SCANNING_FVG,
            SystemState.PENDING_ORDER
        }


# Global singleton instance
state_machine = TradingStateMachine()
