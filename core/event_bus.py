"""
AUREUS-SMC High-Concurrency Asynchronous Event Bus
Provides publish-subscribe decoupled architecture for real-time market events.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Callable, Coroutine, Dict, List, Type, Any
from core.events import BaseEvent

logger = logging.getLogger("EventBus")

HandlerFunc = Callable[[Any], Coroutine[Any, Any, None]]


class AsyncEventBus:
    """
    High-performance asyncio event dispatcher with isolation boundaries.
    Ensures zero cross-contamination of execution latency across listeners.
    """

    def __init__(self) -> None:
        self._handlers: Dict[Type[BaseEvent], List[HandlerFunc]] = {}
        self._global_handlers: List[HandlerFunc] = []
        self._queue: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._is_running: bool = False
        self._worker_task: Optional[asyncio.Task] = None

    def subscribe(self, event_cls: Type[BaseEvent], handler: HandlerFunc) -> None:
        """Register an async callback for a specific event type."""
        if event_cls not in self._handlers:
            self._handlers[event_cls] = []
        if handler not in self._handlers[event_cls]:
            self._handlers[event_cls].append(handler)
            logger.debug(f"Subscribed {handler.__name__} to {event_cls.__name__}")

    def subscribe_all(self, handler: HandlerFunc) -> None:
        """Register a global callback that receives all dispatched events."""
        if handler not in self._global_handlers:
            self._global_handlers.append(handler)

    def unsubscribe(self, event_cls: Type[BaseEvent], handler: HandlerFunc) -> None:
        """Remove a callback from an event type."""
        if event_cls in self._handlers and handler in self._handlers[event_cls]:
            self._handlers[event_cls].remove(handler)

    async def publish(self, event: BaseEvent) -> None:
        """
        Directly and asynchronously invokes all subscribers for the event.
        Uses asyncio.gather with return_exceptions=True for strict fault-tolerance.
        """
        tasks = []
        # Specific handlers
        event_cls = type(event)
        if event_cls in self._handlers:
            for handler in self._handlers[event_cls]:
                tasks.append(self._execute_handler(handler, event))

        # Global handlers
        for handler in self._global_handlers:
            tasks.append(self._execute_handler(handler, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def publish_nowait(self, event: BaseEvent) -> None:
        """Non-blocking queuing for worker background dispatching."""
        self._queue.put_nowait(event)

    async def _execute_handler(self, handler: HandlerFunc, event: BaseEvent) -> None:
        """Wrapper to safely catch and log unhandled exceptions from handlers."""
        try:
            await handler(event)
        except Exception as exc:
            logger.error(f"Error in handler {handler.__name__} processing {type(event).__name__}: {exc}", exc_info=True)

    async def start(self) -> None:
        """Starts background worker if queue-based dispatching is used."""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("AsyncEventBus started successfully.")

    async def stop(self) -> None:
        """Gracefully halts event bus worker."""
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("AsyncEventBus stopped.")

    async def _process_queue(self) -> None:
        """Worker loop consuming queued events."""
        while self._is_running:
            try:
                event = await self._queue.get()
                await self.publish(event)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in EventBus queue loop: {e}", exc_info=True)


# Global singleton instance
event_bus = AsyncEventBus()
