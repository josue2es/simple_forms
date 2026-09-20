"""Shared slowapi rate limiter (keyed on the client's remote address).

Defined here (not in main.py) so that both the REST API routes and the NiceGUI
pages can use the same limiter instance without circular imports; main.py
registers it on app.state.limiter.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

__all__ = ["get_remote_address", "limiter"]
