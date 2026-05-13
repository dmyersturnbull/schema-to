"""Reifier: Python AST → ``.py`` source bytes.

Emits syntactically valid Python that can be parsed with ``ast.parse`` and
formatted by ``ruff format`` without errors.  The output style is:

* ``from __future__ import annotations`` (enables forward references)
* ``from <module> import <names>`` collected from the declaration tree
* PEP 695 ``type Name = ...`` for ``TypeAliasDef``
* ``class Name(BaseModel):`` for ``ClassDef(style=PYDANTIC)``
* ``class Name:`` for plain ``ClassDef``
* Fields as ``name: Annotation`` or ``name: Annotation = default``
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from schema_to._errors import ReificationError, TranspilationError
from schema_to._pipeline import Reifier
from schema_to._result import Err, Ok, Result
from schema_to.ast._python import (
    ClassDef,
    ClassStyle,
    FieldDef,
    FromImport,
    PythonDocString,
    PythonModule,
    PythonTypeAnnotation,
    SimpleImport,
    TypeAliasDef,
)
from schema_to.io._sink import OutputArtifact
from schema_to.io._source import MediaTypes

__all__ = ["PythonReifier"]

_INDENT = "    "


@dataclass(frozen=True)
class PythonReifier(Reifier[PythonModule]):
    """Serialise a ``PythonModule`` AST to a single ``.py`` ``OutputArtifact``.

    Attributes:
        artifact_name: Base file name for the output artifact (e.g. ``"models.py"``).
    """

    artifact_name: str

    def apply(self, input: PythonModule) -> Result[Sequence[OutputArtifact]]:
        try:
            source = self._emit_module(input)
        except Exception as exc:  # noqa: BLE001
            return Err((ReificationError(str(exc)),))
        return Ok([OutputArtifact(
            artifact_id=self.artifact_name,
            content=source.encode("utf-8"),
            media_type=MediaTypes.python,
            source_ids=input.source_ids,
        )])

    # ------------------------------------------------------------------
    # Module
    # ------------------------------------------------------------------

    def _emit_module(self, module: PythonModule) -> str:
        lines: list[str] = []

        if module.module_doc:
            lines += [f'"""{module.module_doc}"""', ""]

        lines += ["from __future__ import annotations", ""]

        for imp in module.imports:
            lines.append(self._emit_import(imp))
        if module.imports:
            lines.append("")

        for i, decl in enumerate(module.declarations):
            if i:
                lines.append("")
            lines += self._emit_decl(decl)

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

    def _emit_import(self, imp: SimpleImport | FromImport) -> str:
        if isinstance(imp, SimpleImport):
            return f"import {imp.module}" + (f" as {imp.alias}" if imp.alias else "")
        names = ", ".join(
            name + (f" as {alias}" if alias else "")
            for name, alias in imp.names
        )
        return f"from {imp.module} import {names}"

    # ------------------------------------------------------------------
    # Top-level declarations
    # ------------------------------------------------------------------

    def _emit_decl(self, decl: TypeAliasDef | ClassDef) -> list[str]:
        if isinstance(decl, TypeAliasDef):
            return self._emit_type_alias(decl)
        return self._emit_class(decl)

    def _emit_type_alias(self, decl: TypeAliasDef) -> list[str]:
        ann = self._emit_annotation(decl.annotation)
        lines: list[str] = []
        if decl.doc:
            lines += self._emit_docstring(decl.doc, indent="")
        lines.append(f"type {decl.name} = {ann}")
        return lines

    def _emit_class(self, decl: ClassDef) -> list[str]:
        lines: list[str] = []

        # Decorators
        for dec in decl.decorators:
            mod = f"{dec.module}." if dec.module else ""
            lines.append(f"@{mod}{dec.name}")

        # Class header
        bases = self._class_bases(decl)
        base_str = f"({', '.join(bases)})" if bases else ""
        lines.append(f"class {decl.name}{base_str}:")

        body: list[str] = []

        # Style-specific config (Pydantic frozen)
        if decl.style == ClassStyle.PYDANTIC_FROZEN:
            body.append(f"{_INDENT}model_config = ConfigDict(frozen=True)")
            body.append("")

        if decl.doc:
            body += self._emit_docstring(decl.doc, indent=_INDENT)

        for f in decl.fields:
            body += self._emit_field(f)

        for m in decl.methods:
            body.append("")
            body += [_INDENT + ln for ln in self._emit_method_stub(m)]

        for nested in decl.nested:
            body.append("")
            body += [_INDENT + ln for ln in self._emit_class(nested)]

        if not body:
            body.append(f"{_INDENT}pass")

        lines += body
        return lines

    def _class_bases(self, decl: ClassDef) -> list[str]:
        style_bases: list[str] = []
        if decl.style in (ClassStyle.PYDANTIC, ClassStyle.PYDANTIC_FROZEN):
            style_bases = ["BaseModel"]
        elif decl.style == ClassStyle.DATACLASS:
            pass  # decorator handles it
        elif decl.style == ClassStyle.FROZEN_DATACLASS:
            pass
        return style_bases + list(decl.bases)

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------

    def _emit_field(self, f: FieldDef) -> list[str]:
        ann = self._emit_annotation(f.annotation)
        line = f"{_INDENT}{f.name}: {ann}"
        if f.default is not None:
            line += f" = {f.default}"
        lines = [line]
        if f.doc:
            lines.append(f'{_INDENT}"""{f.doc}"""')
        return lines

    # ------------------------------------------------------------------
    # Type annotations
    # ------------------------------------------------------------------

    def _emit_annotation(self, ann: PythonTypeAnnotation) -> str:
        base = ann.name
        if ann.args:
            args_str = ", ".join(self._emit_annotation(a) for a in ann.args)
            base = f"{base}[{args_str}]"
        if ann.nullable:
            base = f"{base} | None"
        return base

    # ------------------------------------------------------------------
    # Docstrings
    # ------------------------------------------------------------------

    def _emit_docstring(self, doc: PythonDocString, indent: str) -> list[str]:
        lines: list[str] = []
        text = doc.summary
        if doc.description:
            text += "\n\n" + doc.description
        if "\n" in text:
            lines.append(f'{indent}"""')
            for ln in text.splitlines():
                lines.append(f"{indent}{ln}" if ln.strip() else indent.rstrip())
            lines.append(f'{indent}"""')
        else:
            lines.append(f'{indent}"""{text}"""')
        return lines

    # ------------------------------------------------------------------
    # Method stubs (for abstract methods etc.)
    # ------------------------------------------------------------------

    def _emit_method_stub(self, m: object) -> list[str]:
        return ["pass"]
