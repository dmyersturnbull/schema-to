"""JSON Schema 2020-12 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into a `JsonSchemaDocument` CST.
The parser is **non-resolving**: `$ref` and `$dynamicRef` values are stored as
raw URI strings.  Pass the result to a `RefResolver` stage to inline them.

Errors are accumulated so that a single parse call returns the complete set of
diagnostics rather than stopping at the first fault.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

from schema_to import DefaultJsonLikeReader
from schema_to.cst.base import SourceRef
from schema_to.cst.json_schema import (
    BooleanSchema,
    ConstValue,
    DefaultValue,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    ObjectSchema,
    SchemaType,
)
from schema_to.errors import ParseError, SchemaValidationError, SourceLocation, TranspilationError
from schema_to.io.source import JsonSchemaRawDoc
from schema_to.parse._utils import as_json_dict, as_json_list, decode_raw_doc, ptr
from schema_to.pipeline import DocParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.core import JsonValue
    from schema_to.io.core import JsonLikeReader

__all__ = ["JsonSchemaParser"]


@dataclass(slots=True)
class _ScalarBuckets:
    """Accumulator for the five homogeneous-typed scalar field dicts."""

    str_vals: dict[str, str | None] = field(default_factory=dict)
    bool_vals: dict[str, bool] = field(default_factory=dict)
    int_vals: dict[str, int | None] = field(default_factory=dict)
    float_vals: dict[str, float | None] = field(default_factory=dict)
    list_vals: dict[str, list[JsonValue] | None] = field(default_factory=dict)


loc = SourceLocation

# ---------------------------------------------------------------------------
# Annotation-string → parse-kind lookup table
#
# With `from __future__ import annotations`, every ObjectSchema field
# annotation is stored as a literal string at runtime.  We map those strings
# to a dispatch tag so the data-driven loop can handle each
# JsonValue-compatible field automatically without hard-coding json key names
# in the parser.  Complex fields (JsonSchema, frozenset, ConstValue, …) are
# handled in explicit typed locals and do not appear in this table.
# ---------------------------------------------------------------------------

_KIND_BY_ANNOTATION: dict[str, str] = {
    "str | None": "str",
    "float | None": "num",
    "bool": "bool",
    "int | None": "int",
    "Sequence[JsonValue] | None": "json_array",
}

# Scalar kinds whose values are directly JsonValue-compatible.
_SCALAR_KINDS: frozenset[str] = frozenset(_KIND_BY_ANNOTATION.values()) | {"int_nn"}


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonSchemaParser(DocParser[JsonSchemaRawDoc, JsonSchemaDocument]):
    """Parses JSON or YAML bytes into a `JsonSchemaDocument` CST.

    The parser is stateless: a single instance may be reused across documents.
    """

    reader: JsonLikeReader = field(default_factory=DefaultJsonLikeReader)

    def apply(self, input: JsonSchemaRawDoc) -> Result[JsonSchemaDocument]:
        try:
            raw = decode_raw_doc(input, self.reader)
        except TranspilationError as exc:
            return Err((exc,))
        return self._build_document(raw, document=input)

    def _build_document(
        self, data: JsonValue, *, document: JsonSchemaRawDoc
    ) -> Result[JsonSchemaDocument]:
        root_r = self._build_schema(data, source_id=document.doc_id, pointer="")
        if isinstance(root_r, Err):
            return root_r
        return Ok(
            JsonSchemaDocument(
                root=root_r.value,
                source_id=document.doc_id,
                display_name=document.display_name,
                source_ref=SourceRef(document.doc_id, ""),
            )
        )

    def _build_schema(self, data: JsonValue, *, source_id: str, pointer: str) -> Result[JsonSchema]:
        if isinstance(data, bool):
            return Ok(BooleanSchema(value=data, source_ref=SourceRef(source_id, pointer)))
        if isinstance(data, dict):
            return self._build_object_schema(
                as_json_dict(data), source_id=source_id, pointer=pointer
            )
        return Err(
            (
                ParseError(
                    f"Schema must be `true`, `false`, or an object; got {type(data).__name__!r}.",
                    location=loc(source_id, pointer),
                ),
            )
        )

    def _build_object_schema(  # noqa: PLR0914
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[JsonSchema]:
        """Build an ObjectSchema from a raw JSON object.

        Scalar fields (str, bool, int, float, list[JsonValue]) are collected
        into per-type dicts by a data-driven loop that reads `key` and `kind`
        from each ObjectSchema field's `metadata`.  Complex fields (JsonSchema
        sub-trees, frozensets, wrapper types) are parsed in explicit typed
        locals below the loop.
        """
        errors: list[TranspilationError] = []

        # Per-type dicts for scalar fields — populated by the data-driven loop.
        # Using separate typed containers ensures ObjectSchema() can be
        # constructed with plain .get() calls and no type suppressions.
        buckets = _ScalarBuckets()
        fk: dict[str, str] = {}  # field_name → json_key for ALL keyed fields

        for f in fields(ObjectSchema):
            json_key = f.metadata.get("key")
            if json_key is None:
                continue
            fk[f.name] = json_key
            kind = f.metadata.get("kind") or _KIND_BY_ANNOTATION.get(f.type, "")
            if kind not in _SCALAR_KINDS:
                continue
            self._parse_scalar_field(
                data, json_key, kind, f.name, buckets,
                source_id=source_id, pointer=pointer, errors=errors,
            )

        # -- Complex fields (explicit typed locals) ----------------------------
        schema_type: SchemaType | None = None
        if fk["type"] in data:
            r = self._parse_schema_type(
                data[fk["type"]], location=loc(source_id, ptr(pointer, fk["type"]))
            )
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                schema_type = r.value

        default = DefaultValue(data[fk["default"]]) if fk["default"] in data else None
        const = ConstValue(data[fk["const"]]) if fk["const"] in data else None

        defs = self._build_schema_map(
            data, fk["defs"], source_id=source_id, pointer=pointer, errors=errors
        )
        vocabulary = self._parse_vocabulary(data, source_id=source_id, pointer=pointer, errors=errors)
        required = self._parse_required(data, source_id=source_id, pointer=pointer, errors=errors)
        dependent_required = self._parse_dependent_required(
            data, source_id=source_id, pointer=pointer, errors=errors
        )
        prefix_items = self._build_schema_list(
            data, fk["prefix_items"], source_id=source_id, pointer=pointer, errors=errors
        )
        items = self._build_optional_schema(
            data, fk["items"], source_id=source_id, pointer=pointer, errors=errors
        )
        contains = self._build_optional_schema(
            data, fk["contains"], source_id=source_id, pointer=pointer, errors=errors
        )
        properties = self._build_schema_map(
            data, fk["properties"], source_id=source_id, pointer=pointer, errors=errors
        )
        pattern_properties = self._build_schema_map(
            data, fk["pattern_properties"], source_id=source_id, pointer=pointer, errors=errors
        )
        additional_properties = self._build_optional_schema(
            data, fk["additional_properties"], source_id=source_id, pointer=pointer, errors=errors
        )
        property_names = self._build_optional_schema(
            data, fk["property_names"], source_id=source_id, pointer=pointer, errors=errors
        )
        dependent_schemas = self._build_schema_map(
            data, fk["dependent_schemas"], source_id=source_id, pointer=pointer, errors=errors
        )
        all_of = self._build_schema_list(
            data, fk["all_of"], source_id=source_id, pointer=pointer, errors=errors
        )
        any_of = self._build_schema_list(
            data, fk["any_of"], source_id=source_id, pointer=pointer, errors=errors
        )
        one_of = self._build_schema_list(
            data, fk["one_of"], source_id=source_id, pointer=pointer, errors=errors
        )
        not_ = self._build_optional_schema(
            data, fk["not_"], source_id=source_id, pointer=pointer, errors=errors
        )
        if_ = self._build_optional_schema(
            data, fk["if_"], source_id=source_id, pointer=pointer, errors=errors
        )
        then = self._build_optional_schema(
            data, fk["then"], source_id=source_id, pointer=pointer, errors=errors
        )
        else_ = self._build_optional_schema(
            data, fk["else_"], source_id=source_id, pointer=pointer, errors=errors
        )
        unevaluated_items = self._build_optional_schema(
            data, fk["unevaluated_items"], source_id=source_id, pointer=pointer, errors=errors
        )
        unevaluated_properties = self._build_optional_schema(
            data, fk["unevaluated_properties"], source_id=source_id, pointer=pointer, errors=errors
        )
        content_schema = self._build_optional_schema(
            data, fk["content_schema"], source_id=source_id, pointer=pointer, errors=errors
        )

        if errors:
            return Err(tuple(errors))

        # ObjectSchema is constructed with typed .get() calls so no type
        # suppressions are needed: each dict has a homogeneous value type that
        # matches the corresponding ObjectSchema field type exactly.
        sv, bv, iv, fv, lv = (
            buckets.str_vals, buckets.bool_vals, buckets.int_vals,
            buckets.float_vals, buckets.list_vals,
        )
        schema: JsonSchema = ObjectSchema(
            # Scalar fields from the data-driven loop
            id=sv.get("id"),
            schema=sv.get("schema"),
            anchor=sv.get("anchor"),
            dynamic_anchor=sv.get("dynamic_anchor"),
            ref=sv.get("ref"),
            dynamic_ref=sv.get("dynamic_ref"),
            comment=sv.get("comment"),
            title=sv.get("title"),
            description=sv.get("description"),
            deprecated=bv.get("deprecated", False),
            read_only=bv.get("read_only", False),
            write_only=bv.get("write_only", False),
            unique_items=bv.get("unique_items", False),
            multiple_of=fv.get("multiple_of"),
            maximum=fv.get("maximum"),
            exclusive_maximum=fv.get("exclusive_maximum"),
            minimum=fv.get("minimum"),
            exclusive_minimum=fv.get("exclusive_minimum"),
            max_length=iv.get("max_length"),
            min_length=iv.get("min_length"),
            pattern=sv.get("pattern"),
            min_contains=iv.get("min_contains"),
            max_contains=iv.get("max_contains"),
            min_items=iv.get("min_items"),
            max_items=iv.get("max_items"),
            min_properties=iv.get("min_properties"),
            max_properties=iv.get("max_properties"),
            content_encoding=sv.get("content_encoding"),
            content_media_type=sv.get("content_media_type"),
            format=sv.get("format"),
            examples=lv.get("examples"),
            enum=lv.get("enum"),
            # Complex fields
            type=schema_type,
            default=default,
            const=const,
            defs=defs,
            vocabulary=vocabulary,
            required=required,
            dependent_required=dependent_required,
            prefix_items=prefix_items,
            items=items,
            contains=contains,
            properties=properties,
            pattern_properties=pattern_properties,
            additional_properties=additional_properties,
            property_names=property_names,
            dependent_schemas=dependent_schemas,
            all_of=all_of,
            any_of=any_of,
            one_of=one_of,
            not_=not_,
            if_=if_,
            then=then,
            else_=else_,
            unevaluated_items=unevaluated_items,
            unevaluated_properties=unevaluated_properties,
            content_schema=content_schema,
            extensions={k: v for k, v in data.items() if k.startswith("x-")},
            source_ref=SourceRef(source_id, pointer),
        )
        return Ok(schema)

    # -- Scalar field dispatcher ----------------------------------------------

    def _parse_scalar_field(  # noqa: C901
        self,
        data: dict[str, JsonValue],
        json_key: str,
        kind: str,
        field_name: str,
        buckets: _ScalarBuckets,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> None:
        """Parse one scalar ObjectSchema field and deposit the result into the appropriate typed dict."""
        if json_key not in data:
            if kind == "bool":
                buckets.bool_vals[field_name] = False
            return
        raw = data[json_key]
        match kind:
            case "str":
                buckets.str_vals[field_name] = raw if isinstance(raw, str) else None
            case "num":
                buckets.float_vals[field_name] = (
                    raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
                )
            case "bool":
                buckets.bool_vals[field_name] = bool(raw)
            case "int":
                buckets.int_vals[field_name] = (
                    raw if isinstance(raw, int) and not isinstance(raw, bool) else None
                )
            case "int_nn":
                if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                    buckets.int_vals[field_name] = raw
                else:
                    errors.append(
                        SchemaValidationError(
                            f"{json_key} must be a non-negative integer.",
                            location=loc(source_id, ptr(pointer, json_key)),
                        )
                    )
            case "json_array":
                if isinstance(raw, list):
                    buckets.list_vals[field_name] = as_json_list(raw)
                else:
                    errors.append(
                        SchemaValidationError(
                            f"{json_key} must be an array.",
                            location=loc(source_id, ptr(pointer, json_key)),
                        )
                    )

    # -- Vocabulary sub-parsers -----------------------------------------------

    def _parse_vocabulary(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> dict[str, bool] | None:
        if "$vocabulary" not in data:
            return None
        raw_vocab = data["$vocabulary"]
        if not isinstance(raw_vocab, dict):
            errors.append(
                SchemaValidationError(
                    "$vocabulary must be an object.",
                    location=loc(source_id, ptr(pointer, "$vocabulary")),
                )
            )
            return None
        vocab_d = as_json_dict(raw_vocab)
        vocabulary: dict[str, bool] = {}
        for uri, required in vocab_d.items():
            if not isinstance(required, bool):
                errors.append(
                    SchemaValidationError(
                        f"$vocabulary value for {uri!r} must be a boolean.",
                        location=loc(source_id, ptr(pointer, "$vocabulary", uri)),
                    )
                )
            else:
                vocabulary[uri] = required
        return vocabulary

    def _parse_required(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> frozenset[str] | None:
        if "required" not in data:
            return None
        raw_req = data["required"]
        if not isinstance(raw_req, list) or not all(isinstance(s, str) for s in raw_req):
            errors.append(
                SchemaValidationError(
                    "required must be an array of strings.",
                    location=loc(source_id, ptr(pointer, "required")),
                )
            )
            return None
        # The `all(isinstance(s, str) for s in raw_req)` guard above ensures every element
        # is a str; the isinstance filter below is redundant but satisfies the type checker.
        return frozenset(x for x in raw_req if isinstance(x, str))

    def _parse_dependent_required(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> dict[str, frozenset[str]] | None:
        if "dependentRequired" not in data:
            return None
        raw_dr = data["dependentRequired"]
        if not isinstance(raw_dr, dict):
            errors.append(
                SchemaValidationError(
                    "dependentRequired must be an object.",
                    location=loc(source_id, ptr(pointer, "dependentRequired")),
                )
            )
            return None
        dr_d = as_json_dict(raw_dr)
        dependent_required: dict[str, frozenset[str]] = {}
        for prop, deps in dr_d.items():
            if not isinstance(deps, list) or not all(isinstance(s, str) for s in deps):
                errors.append(
                    SchemaValidationError(
                        f"dependentRequired[{prop!r}] must be an array of strings.",
                        location=loc(source_id, ptr(pointer, "dependentRequired", prop)),
                    )
                )
            else:
                # The `all(isinstance(s, str) for s in deps)` guard above ensures every element
                # is a str; the isinstance filter below is redundant but satisfies the type checker.
                dependent_required[prop] = frozenset(x for x in deps if isinstance(x, str))
        return dependent_required

    # -- Reusable sub-builders ------------------------------------------------

    def _parse_schema_type(
        self, value: JsonValue, *, location: SourceLocation
    ) -> Result[SchemaType]:
        if isinstance(value, str):
            try:
                return Ok(JsonSchemaType(value))
            except ValueError:
                return Err(
                    (
                        SchemaValidationError(
                            f"Unknown primitive type: {value!r}.", location=location
                        ),
                    )
                )
        if isinstance(value, list):
            types: list[JsonSchemaType] = []
            errs: list[TranspilationError] = []
            for item in as_json_list(value):
                if not isinstance(item, str):
                    errs.append(
                        SchemaValidationError(
                            "type array elements must be strings.", location=location
                        )
                    )
                    continue
                try:
                    types.append(JsonSchemaType(item))
                except ValueError:
                    errs.append(
                        SchemaValidationError(
                            f"Unknown primitive type: {item!r}.", location=location
                        )
                    )
            if errs:
                return Err(tuple(errs))
            return Ok(frozenset(types))
        return Err(
            (
                SchemaValidationError(
                    f"type must be a string or array, got {type(value).__name__!r}.",
                    location=location,
                ),
            )
        )

    def _build_optional_schema(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> JsonSchema | None:
        if key not in data:
            return None
        r = self._build_schema(data[key], source_id=source_id, pointer=ptr(pointer, key))
        if isinstance(r, Err):
            errors.extend(r.errors)
            return None
        return r.value

    def _build_schema_list(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[JsonSchema] | None:
        if key not in data:
            return None
        raw = data[key]
        if not isinstance(raw, list):
            errors.append(
                SchemaValidationError(
                    f"{key} must be an array.", location=loc(source_id, ptr(pointer, key))
                )
            )
            return None
        result: list[JsonSchema] = []
        for i, item in enumerate(as_json_list(raw)):
            r = self._build_schema(item, source_id=source_id, pointer=ptr(pointer, key, i))
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                result.append(r.value)
        return result

    def _build_schema_map(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> dict[str, JsonSchema] | None:
        if key not in data:
            return None
        raw = data[key]
        if not isinstance(raw, dict):
            errors.append(
                SchemaValidationError(
                    f"{key} must be an object.", location=loc(source_id, ptr(pointer, key))
                )
            )
            return None
        result: dict[str, JsonSchema] = {}
        for name, value in as_json_dict(raw).items():
            r = self._build_schema(value, source_id=source_id, pointer=ptr(pointer, key, name))
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                result[name] = r.value
        return result
