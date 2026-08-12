"""Transpiler: JSON Schema 2020-12 → Pydantic v2 Python models."""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, override

from schema_to.generate._names import safe_python_field_name
from schema_to.generate.pydantic import PydanticTransformer
from schema_to.io.core import DefaultJsonLikeReader
from schema_to.io.sink import PythonArtifact
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse.json_schema import JsonSchemaParser
from schema_to.pipeline import Transpiler
from schema_to.reify.python import PythonReifier
from schema_to.resolve.json_schema import JsonSchemaRefResolver
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from collections.abc import Sequence

    from schema_to.ast.python import PythonModule
    from schema_to.cst.json_schema import JsonSchemaDocument
    from schema_to.errors import TranspilationWarning

__all__ = ["JsonSchemaToPydanticTranspiler"]


@dataclass(frozen=True, slots=True)
class JsonSchemaToPydanticTranspiler(Transpiler[JsonSchemaRawDoc, PythonArtifact]):
    """End-to-end transpiler: JSON Schema 2020-12 → Pydantic v2 `BaseModel` classes."""

    parser: JsonSchemaParser = field(
        default_factory=lambda: JsonSchemaParser(reader=DefaultJsonLikeReader())
    )
    resolver: JsonSchemaRefResolver = field(default_factory=JsonSchemaRefResolver)
    generator: PydanticTransformer = field(default_factory=PydanticTransformer)
    reifier: PythonReifier = field(default_factory=lambda: PythonReifier(artifact_id="models.py"))
    output_name: str = "models.py"

    @override
    @property
    def warnings(self) -> Sequence[TranspilationWarning]:
        return list(self.generator.warnings)

    @override
    def accepts(self, doc: JsonSchemaRawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    @override
    def transpile_all(self, docs: Sequence[JsonSchemaRawDoc]) -> Result[Sequence[PythonArtifact]]:
        """Name each artifact after its document when the batch holds more than one.

        A single document keeps the configured `output_name`, which is what a caller
        transpiling one schema asked for.  Several cannot all keep it: they would
        overwrite one another in the sink, leaving whichever ran last.
        """
        result = super().transpile_all(docs)
        if len(docs) < 2 or isinstance(result, Err):
            return result
        named = [
            replace(artifact, artifact_id=_module_name(doc, self.output_name))
            for doc, artifact in zip(docs, result.value, strict=False)
        ]
        return Ok(named)

    @override
    def transpile(self, doc: JsonSchemaRawDoc) -> Result[Sequence[PythonArtifact]]:
        # Stage 1: parse
        r1 = self.parser.apply(doc)
        if isinstance(r1, Err):
            return r1
        cst: JsonSchemaDocument = r1.value
        # Stage 2: resolve
        r2 = self.resolver.apply(cst)
        if isinstance(r2, Err):
            return r2
        # Stage 3: generate
        gen = PydanticTransformer(resolver=self.resolver)
        r3 = gen.apply(r2.value)
        if isinstance(r3, Err):
            return r3
        module: PythonModule = r3.value
        # Stage 4: reify
        reifier = PythonReifier(artifact_id=self.output_name)
        return reifier.apply(module)


def _module_name(doc: JsonSchemaRawDoc, fallback: str) -> str:
    """Return a module file name for `doc`, derived from its display name."""
    if not doc.display_name:
        return fallback
    return f"{safe_python_field_name(doc.display_name)}.py"
