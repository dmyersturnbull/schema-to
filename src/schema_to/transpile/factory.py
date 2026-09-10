"""Composition root: build the `Transpiler`s for a target name.

The `--to` CLI option is a string that names a target format.
This module is the one place that knows which stages a target is made of,
which keeps every other module free of target-specific wiring:
A parser does not know what will consume its CST,
and a generator does not know where its AST will be written.

A target is a composed `Stage`, not a class.
All of them have the same shape:

```
Sequence[RawDoc] → parse → resolve → generate → reify → Sequence[Artifact]
```

They differ only in which stages fill those slots,
and in whether the batch or the single document is the unit.
[schema_to.pipeline.Each][]
lifts a per-document chain over a batch;
a target whose output depends on the whole set uses a stage that takes the batch directly.

Shared state is threaded in from here rather than discovered at run time:
The one [JsonSchemaRefResolver][] a target uses is constructed here and handed to every stage that needs it,
so no stage has to ask another whether it happens to have one.

"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence, Set
from enum import Enum
from types import get_original_bases
from typing import get_args

from schema_to.io.media_type import MediaType
from schema_to.pipeline import Transpiler

__all__ = ["AbstractTranspilerRouter", "RoutingError", "UnknownTargetError"]


class RoutingError(Exception):
    """Raised if the router could not map the inputs to transpilers."""


class UnknownTargetError(RoutingError):
    """Raised if an unrecognised target name was provided."""

    def __init__(self, *, value: str, supported: Set[str]) -> None:
        msg = f"Target {value!r} is not supported; choose one of: {', '.join(sorted(supported))}"
        super().__init__(msg)


class AbstractTranspilerRouter[T: Enum](ABC):
    """Assembles the stages a target is made of into the transpilers that run it."""

    def enum(self) -> type[T]:
        return get_args(get_original_bases(type(self))[0])[0]

    def route(
        self,
        target: str | T,
        output_media_type: MediaType,
        *,
        templates: Mapping[str, str] | None = None,
        roots: Set[str] | None = None,
        schema_map: bool = False,
    ) -> Sequence[Transpiler]:
        """Return the ordered list of transpilers for target `target`.

        Args:
            target: The requested target format.
            output_media_type: Media type for re-emitted schema sources.
            templates: Named endpoint-body Jinja templates (`fastapi` target),
                registered from the CLI's `--template <name>=<path>`.
            roots: If given, restricts which named schema nodes become their own artifact —
                a `$defs` entry (JSON Schema), a schema-map entry, or a `components/schemas` entry (OpenAPI).
                Every other schema stays available for `$ref` resolution.
                `None` generates every one.
            schema_map: Read each source document as a map of named schemas rather than as one schema.
                Each target is then met on its own terms:
                one whose unit is the whole set consumes it directly,
                and one whose unit is a single schema is fed the schemas one at a time.

        Raises:
            RoutingError: If `target_name` is not recognized or supported.
        """
        if isinstance(target, str):
            t = self.enum()
            try:
                target = t(target)
            except ValueError:
                raise UnknownTargetError(
                    value=target, supported=frozenset(m.value for m in t)
                ) from None
        return self._route(target, output_media_type, templates, roots, schema_map=schema_map)

    @abstractmethod
    def _route(
        self,
        target: T,
        output_media_type: MediaType,
        templates: Mapping[str, str] | None,
        roots: Set[str] | None,
        *,
        schema_map: bool,
    ) -> Sequence[Transpiler]:
        raise NotImplementedError
