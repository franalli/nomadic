"""SSE connection tracking state.

Extracted from main.py to break the circular import between main.py and lifespan.py.
Both modules import from here instead of from each other.
"""

import asyncio
from collections import defaultdict

# SSE concurrent connection tracking
_sse_connections: dict[str, int] = defaultdict(int)
_sse_state_lock = asyncio.Lock()

MAX_SSE_PER_SESSION = 2
MAX_SSE_PER_IP = 5
