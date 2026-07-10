"""Shared slowapi Limiter instance.

Lives in its own module (not app/main.py) so route files can import and
decorate endpoints with `@limiter.limit(...)` without a circular import back
to the FastAPI app factory.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
