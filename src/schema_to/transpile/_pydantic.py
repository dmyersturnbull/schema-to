"""Transpiler: JSON Schema 2020-12 → Pydantic v2 Python models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from schema_to._errors import TranspilationWarning
from schema_to._pipeline import Transpiler
from schema_to._result import Err, Ok, Result
from schema_to.ast._python import PythonModule
from schema_to.cst._json_schema import JsonSchemaDocument
from schema_to.generate._pydantic import PydanticGenerator
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import (
    JsonSchemaRawDocument,
    MediaTypes,
    OpenApiRawDocument,
    RawDocument,
)
from schema_to.parse._json_schema import JsonSchemaParser
from schema_to.reify._python import PythonReifier
from schema_to.resolve._json_schema import JsonSchemaRefResolver

__all__ = ["JsonSchemaToPydanticTranspiler"]

_JSON_YAML_ESSENCES = frozenset({"application/json", "application/yaml", "text/yaml"})


@dataclass(frozen=True)
class JsonSchemaToPydanticTranspiler(Transpiler):
    """End-to-end transpiler: JSON Schema 2020-12 → Pydantic v2 ``BaseModel`` classes.

    The four pipeline stages are:

    1. **parse** — ``JsonSchemaParser`` decodes JSON/YAML to a ``JsonSchemaDocument`` CST.
    2. **resolve** — ``JsonSchemaRefResolver`` validates all ``$ref`` / ``$dynamicRef`` links.
    3. **generate** — ``PydanticGenerator`` maps the CST to a ``PythonModule`` AST.
    4. **reify** — ``PythonReifier`` serialises the AST to ``.py`` bytes.

    Attributes:
        parser: JSON Schema parser (injected for testability).
        resolver: Ref resolver shared across documents (injected for testability).
        generator: Pydantic code generator (injected for testability).
        reifier: Python source reifier (injected for testability).
        output_name: Base name for the emitted ``.py`` artifact.
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
        if document.media_type.essence not in _JSON_YAML_ESSENCES:
            return False
        # Peek to ensure it's not OpenAPI.
        try:
            import orjson  # noqa: PLC0415
            if document.media_type.essence == "application/json":
                data = orjson.loads(document.content)
            else:
                from yaml12 import parse_yaml  # noqa: PLC0415
                data = parse_yaml(document.content.decode("utf-8"))
            return not (isinstance(data, dict) and isinstance(data.get("openapi"), str))
        except Exception:  # noqa: BLE001
            return False

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
