"""
SSE (Server-Sent Events) endpoint for real-time updates.

Streams platform events to the frontend as they happen.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


async def event_stream() -> AsyncGenerator[str, None]:
    """Generate SSE events.

    In production, this would read from a Redis Pub/Sub channel
    or a PostgreSQL LISTEN/NOTIFY stream. For now, it sends a
    heartbeat every 15 seconds to keep the connection alive.
    """
    while True:
        event = {
            "type": "heartbeat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        yield f"data: {json.dumps(event)}\n\n"
        await asyncio.sleep(15)


async def sse_endpoint():
    """FastAPI route handler for the SSE stream."""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
