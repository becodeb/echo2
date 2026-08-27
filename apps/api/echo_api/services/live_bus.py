"""Bus pub/sub en memoria para eventos de reuniones en vivo.

Cada reunión tiene un canal. Los viewers (WebSocket) se suscriben y reciben
segmentos de transcript, insights incrementales y cambios de estado.
"""
import asyncio
import logging
from collections import defaultdict

log = logging.getLogger("echo.live")


class LiveBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        async with self._lock:
            self._subscribers[channel].add(queue)
        return queue

    async def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers[channel].discard(queue)
            if not self._subscribers[channel]:
                del self._subscribers[channel]

    async def publish(self, channel: str, message: dict) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(channel, ()))
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                log.warning("live_bus: cola llena, descartando evento en canal %s", channel)


live_bus = LiveBus()
