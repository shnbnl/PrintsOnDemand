"""Database-backed fixed-window limits for security-sensitive requests.

The database is shared across WSGI workers. Counter keys are HMACs so account
identifiers and client addresses are not stored in the counter table.
"""

import hashlib
import hmac
import secrets
import time

from flask import abort, current_app, g, request
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.rate_limit import RateLimitBucket


def client_address() -> str:
    """Use the WSGI peer, not untrusted forwarding headers supplied by clients."""
    return request.remote_addr or "unknown"


def enforce_limit(scope: str, identity: str, *, attempts: int, seconds: int) -> None:
    now = int(time.time())
    start = now - now % seconds
    raw = f"{scope}:{seconds}:{start}:{identity}".encode("utf-8")
    key = hmac.new(current_app.secret_key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    table = RateLimitBucket.__table__
    for _ in range(2):
        try:
            # Keep limiter writes out of the request's ORM transaction.
            with db.engine.begin() as connection:
                changed = connection.execute(
                    update(table).where(table.c.key == key, table.c.hits < attempts)
                    .values(hits=table.c.hits + 1)
                )
                if changed.rowcount:
                    return
                if connection.scalar(select(table.c.key).where(table.c.key == key)):
                    break
                connection.execute(insert(table).values(key=key, window_start=start, hits=1))
                if secrets.randbelow(256) == 0:
                    connection.execute(delete(table).where(table.c.window_start < now - 2 * 86400))
                return
        except IntegrityError:
            # A second worker inserted the first bucket concurrently.
            continue
    current_app.logger.warning("Sensitive request rate limit reached: %s", scope)
    g.rate_limit_retry_after = seconds - (now - start)
    abort(429)
