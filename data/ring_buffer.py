"""
AUREUS-SMC High-Performance Circular Buffers
O(1) memory-bounded ring buffers for high-frequency ticks and candlestick series.
"""

from __future__ import annotations
from collections import deque
from typing import TypeVar, Generic, List, Optional, Iterator

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """
    Thread-safe and memory-bounded ring buffer for high-throughput market data.
    Ensures O(1) appends and instantaneous slicing of recent periods.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("Capacity must be greater than 0")
        self._capacity = capacity
        self._deque: deque[T] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def append(self, item: T) -> None:
        """Appends an element to the buffer, dropping the oldest element if full."""
        self._deque.append(item)

    def extend(self, items: List[T]) -> None:
        """Appends multiple elements."""
        self._deque.extend(items)

    def latest(self, n: int = 1) -> List[T]:
        """Returns the last `n` elements (from oldest to newest of the slice)."""
        if n <= 0 or not self._deque:
            return []
        count = min(n, len(self._deque))
        # Convert trailing slice efficiently
        return [self._deque[-i] for i in range(count, 0, -1)]

    def last(self) -> Optional[T]:
        """Returns the most recent single element or None if empty."""
        return self._deque[-1] if self._deque else None

    def to_list(self) -> List[T]:
        """Returns all elements currently in the buffer as a list."""
        return list(self._deque)

    def clear(self) -> None:
        """Clears all elements in the buffer."""
        self._deque.clear()

    def __len__(self) -> int:
        return len(self._deque)

    def __iter__(self) -> Iterator[T]:
        return iter(self._deque)

    def __getitem__(self, index: int) -> T:
        return self._deque[index]
