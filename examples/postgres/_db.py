"""Application database glue for the generated FastAPI app.

query-dsl builds queries but knows nothing about FastAPI's dependency injection or Pydantic.
This small module supplies the two pieces of app glue the generated endpoint bodies import:
(1) a connection dependency and (2) request-body-to-dict coercion.
Replace `get_db` with a real provider before serving traffic;
for example, you might use one backed by a `psycopg_pool.AsyncConnectionPool`.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection


async def get_db() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency yielding a database connection (stub)."""
    msg = "Configure get_db() with a psycopg AsyncConnection provider."
    raise NotImplementedError(msg)
    yield  # pragma: no cover - makes this an async generator


def to_dict(body: Any) -> Mapping[str, Any]:
    """Coerce a request body (Pydantic model or mapping) to a plain dict."""
    dump = getattr(body, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return dict(body)
