"""Transpiler: OpenAPI 3.1 → FastAPI application Python module."""


from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from schema_to.generate.fastapi import FastApiTransformer
from schema_to.io.core import DefaultJsonLikeReader
from schema_to.io.sink import PythonArtifact
from schema_to.io.source import OpenApiRawDoc
from schema_to.parse.openapi import OpenApiParser
from schema_to.pipeline import Transpiler
from schema_to.reify.python import PythonReifier
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.cst.openapi import OpenApiDocument
    from schema_to.errors import TranspilationWarning

__all__ = ["OpenApiToFastApiTranspiler"]


@dataclass(frozen=True, slots=True)
class OpenApiToFastApiTranspiler(Transpiler[OpenApiRawDoc, PythonArtifact]):
    """End-to-end transpiler: OpenAPI 3.1 → FastAPI application module.

    The four pipeline stages are:

    1. **Parse** – `OpenApiParser` decodes JSON/YAML bytes into an `OpenApiDocument` CST.
       Embedded JSON Schemas are parsed via the same `JsonSchemaParser` used by the
       JSON Schema → Pydantic pipeline.
    2. **Generate** – `FastApiTransformer` converts the `OpenApiDocument` into a
       `PythonModule` AST containing Pydantic model classes and async route functions.
       Component schemas are routed through `PydanticTransformer` internally.
    3. **Reify** – `PythonReifier` serialises the `PythonModule` to a `.py` artifact.

    There is no dedicated resolve stage: `$ref` values within component schemas are
    resolved at generation time by the embedded `PydanticTransformer`.
    """

    parser: OpenApiParser = field(
        default_factory=lambda: OpenApiParser(reader=DefaultJsonLikeReader())
    )
    generator: FastApiTransformer = field(default_factory=FastApiTransformer)
    reifier: PythonReifier = field(default_factory=lambda: PythonReifier(artifact_id="main.py"))
    output_name: str = "main.py"

    @override
    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    @override
    def accepts(self, doc: OpenApiRawDoc) -> bool:
        return isinstance(doc, OpenApiRawDoc)

    @override
    def transpile(self, doc: OpenApiRawDoc) -> Result[Sequence[PythonArtifact]]:
        # Stage 1: parse
        r1 = self.parser.apply(doc)
        if isinstance(r1, Err):
            return r1
        cst: OpenApiDocument = r1.value
        # Stage 2: generate (the configured generator carries the body backend)
        r2 = self.generator.apply(cst)
        if isinstance(r2, Err):
            return r2
        # Stage 3: reify, then append any support modules the backend needs.
        reifier = PythonReifier(artifact_id=self.output_name)
        r3 = reifier.apply(r2.value)
        if isinstance(r3, Err):
            return r3
        return Ok([*r3.value, *self.generator.body_backend.support_artifacts()])
