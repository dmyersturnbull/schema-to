"""Transpiler: JSON Schema 2020-12 → Pydantic v2 Python models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from schema_to.transpile.utils import JSON_YAML_ESSENCES, peek_is_openapi

from schema_to.generate.pydantic import PydanticGenerator
from schema_to.io.source import JsonSchemaRawDocument, OpenApiRawDocument, RawDocument
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import Transpiler
from schema_to.reify.python import PythonReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.ast.python import PythonModule
    from schema_to.cst.json_schema import JsonSchemaDocument
    from schema_to.errors import TranspilationWarning
    from schema_to.io.sink import OutputArtifact

__all__ = ["JsonSchemaToPydanticTranspiler"]


@dataclass(frozen=True)
class JsonSchemaToPydanticTranspiler(Transpiler):
    """End-to-end transpiler: JSON Schema 2020-12 → Pydantic v2 `BaseModel` classes.

    The four pipeline stages are:

    1. **parse** — `JsonSchemaParser` decodes JSON/YAML to a `JsonSchemaDocument` CST.
    2. **resolve** — `JsonSchemaRefResolver` validates all `$ref` / `$dynamicRef` links.
    3. **generate** — `PydanticGenerator` maps the CST to a `PythonModule` AST.
    4. **reify** — `PythonReifier` serialises the AST to `.py` bytes.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        resolver: Ref resolver shared across documents (injected for testability).
        generator: Pydantic code generator (injected for testability).
        reifier: Python source reifier (injected for testability).
        output_name: Base name for the emitted `.py` artifact.
    """

    parser: JsonSchemaParser = field(default_factory=JsonSchemaParser)
    resolver: JsonSchemaRefResolver = field(default_factory=JsonSchemaRefResolver)
    generator: PydanticGenerator = field(default_factory=PydanticGenerator)
    reifier: PythonReifier = field(default_factory=lambda: PythonReifier(artifact_name="models.py"))
    output_name: str = "models.py"

    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    def accepts(self, document: RawDocument) -> bool:
        if isinstance(document, JsonSchemaRawDocument):
            return True
        if isinstance(document, OpenApiRawDocument):
            return False
        return document.media_type.essence in JSON_YAML_ESSENCES and not peek_is_openapi(document)

    def transpile(self, document: RawDocument) -> Result[Sequence[OutputArtifact]]:
        # Stage 1: parse
        r1 = self.parser.apply(document)
        if isinstance(r1, Err):
            return r1
        cst: JsonSchemaDocument = r1.value

        # Stage 2: resolve
        r2 = self.resolver.apply(cst)
        if isinstance(r2, Err):
            return r2

        # Stage 3: generate
        gen = PydanticGenerator(resolver=self.resolver)
        r3 = gen.apply(r2.value)
        if isinstance(r3, Err):
            return r3
        module: PythonModule = r3.value

        # Stage 4: reify
        reifier = PythonReifier(artifact_name=self.output_name)
        return reifier.apply(module)
