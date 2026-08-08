"""JSON Schema 2020-12 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into a `JsonSchemaDocument` CST.
The parser is **non-resolving**: `$ref` and `$dynamicRef` values are stored as
raw URI strings.  Pass the result to a `RefResolver` stage to inline them.

Errors are accumulated so that a single parse call returns the complete set of
diagnostics rather than stopping at the first fault.
"""

from collections.abc import Mapping, MutableSequence
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


# Union of every type that can appear as an ObjectSchema field value.
# Used as the value type for the data-driven kwargs dict so that individual
# assignments type-check without resorting to `Any` or `object`.
type _SchemaFieldValue = (
    str
    | bool
    | int
    | float
    | list[JsonValue]
    | JsonSchemaType
    | frozenset[JsonSchemaType]
    | frozenset[str]
    | DefaultValue
    | ConstValue
    | JsonSchema
    | list[JsonSchema]
    | dict[str, JsonSchema]
    | dict[str, bool]
    | dict[str, frozenset[str]]
    | dict[str, JsonValue]
    | SourceRef
    | None
)


loc = SourceLocation


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
        if isinstance(data, Mapping):
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

    def _build_object_schema(
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[JsonSchema]:
        """Build an `ObjectSchema` from a raw JSON object.

        A data-driven loop reads `key` and `kind` from each `ObjectSchema`
        field's `metadata` and dispatches to `_parse_field_into`, which
        deposits the parsed value into `kwargs`.  Adding a new field to
        `ObjectSchema` (with both metadata entries) requires no change here.

        Synthetic fields (`extensions`, `source_ref`) carry no `key`;
        they are appended after the loop.
        """
        errors: list[TranspilationError] = []
        kwargs: dict[str, _SchemaFieldValue] = {}

        for f in fields(ObjectSchema):
            json_key = f.metadata.get("key")
            kind = f.metadata.get("kind")
            if json_key is None or kind is None:
                continue  # synthetic field (extensions, source_ref) — handled below
            self._parse_field_into(
                data,
                f.name,
                json_key,
                kind,
                kwargs,
                source_id=source_id,
                pointer=pointer,
                errors=errors,
            )

        kwargs["extensions"] = {k: v for k, v in data.items() if k.startswith("x-")}
        kwargs["source_ref"] = SourceRef(source_id, pointer)

        if errors:
            return Err(tuple(errors))

        schema: JsonSchema = ObjectSchema(**kwargs)  # ty: ignore[invalid-argument-type]
        return Ok(schema)

    # -- Unified field dispatcher ---------------------------------------------

    # ruff:ignore[complex-structure, too-many-branches]  # Shared structure
    def _parse_field_into(
        self,
        data: dict[str, JsonValue],
        field_name: str,
        json_key: str,
        kind: str,
        kwargs: dict[str, _SchemaFieldValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> None:
        """Parse one `ObjectSchema` field and deposit the result into `kwargs`."""
        match kind:
            case "schema_type":
                if json_key in data:
                    r = self._parse_schema_type(
                        data[json_key], location=loc(source_id, ptr(pointer, json_key))
                    )
                    if isinstance(r, Err):
                        errors.extend(r.errors)
                    else:
                        kwargs[field_name] = r.value
            case "default_value":
                if json_key in data:
                    kwargs[field_name] = DefaultValue(data[json_key])
            case "const_value":
                if json_key in data:
                    kwargs[field_name] = ConstValue(data[json_key])
            case "schema_map":
                kwargs[field_name] = self._build_schema_map(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case "bool_map":
                kwargs[field_name] = self._parse_bool_map(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case "str_frozenset":
                kwargs[field_name] = self._parse_str_frozenset(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case "dep_required_map":
                kwargs[field_name] = self._parse_dep_required_map(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case "optional_schema":
                kwargs[field_name] = self._build_optional_schema(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case "schema_list":
                kwargs[field_name] = self._build_schema_list(
                    data, json_key, source_id=source_id, pointer=pointer, errors=errors
                )
            case _:
                self._parse_scalar_into(
                    data,
                    field_name,
                    json_key,
                    kind,
                    kwargs,
                    source_id=source_id,
                    pointer=pointer,
                    errors=errors,
                )

    # ruff:ignore[complex-structure, too-many-branches]  # Mostly shared structure
    def _parse_scalar_into(
        self,
        data: dict[str, JsonValue],
        field_name: str,
        json_key: str,
        kind: str,
        kwargs: dict[str, _SchemaFieldValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> None:
        """Parse one scalar `ObjectSchema` field into `kwargs`."""
        match kind:
            case "str":
                raw = data.get(json_key)
                if isinstance(raw, str):
                    kwargs[field_name] = raw
            case "num":
                raw = data.get(json_key)
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    kwargs[field_name] = float(raw)
            case "bool":
                kwargs[field_name] = bool(data.get(json_key))
            case "int":
                raw = data.get(json_key)
                if isinstance(raw, int) and not isinstance(raw, bool):
                    kwargs[field_name] = raw
            case "int_nn" if json_key in data:
                raw = data[json_key]
                if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                    kwargs[field_name] = raw
                else:
                    errors.append(
                        SchemaValidationError(
                            f"{json_key} must be a non-negative integer.",
                            location=loc(source_id, ptr(pointer, json_key)),
                        )
                    )
            case "json_array" if json_key in data:
                raw = data[json_key]
                if isinstance(raw, MutableSequence):
                    kwargs[field_name] = as_json_list(raw)
                else:
                    errors.append(
                        SchemaValidationError(
                            f"{json_key} must be an array.",
                            location=loc(source_id, ptr(pointer, json_key)),
                        )
                    )

    # -- Vocabulary sub-parsers -----------------------------------------------

    def _parse_bool_map(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> dict[str, bool] | None:
        if key not in data:
            return None
        raw = data[key]
        if not isinstance(raw, Mapping):
            errors.append(
                SchemaValidationError(
                    f"{key} must be an object.", location=loc(source_id, ptr(pointer, key))
                )
            )
            return None
        result: dict[str, bool] = {}
        for uri, val in as_json_dict(raw).items():
            if not isinstance(val, bool):
                errors.append(
                    SchemaValidationError(
                        f"{key} value for {uri!r} must be a boolean.",
                        location=loc(source_id, ptr(pointer, key, uri)),
                    )
                )
            else:
                result[uri] = val
        return result

    def _parse_str_frozenset(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> frozenset[str] | None:
        if key not in data:
            return None
        raw = data[key]
        if not isinstance(raw, MutableSequence) or not all(isinstance(s, str) for s in raw):
            errors.append(
                SchemaValidationError(
                    f"{key} must be an array of strings.",
                    location=loc(source_id, ptr(pointer, key)),
                )
            )
            return None
        # The `all(isinstance(s, str) for s in raw)` guard above ensures every element
        # is a str; the isinstance filter below is redundant but satisfies the type checker.
        return frozenset(x for x in raw if isinstance(x, str))

    def _parse_dep_required_map(
        self,
        data: dict[str, JsonValue],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> dict[str, frozenset[str]] | None:
        if key not in data:
            return None
        raw = data[key]
        if not isinstance(raw, Mapping):
            errors.append(
                SchemaValidationError(
                    f"{key} must be an object.", location=loc(source_id, ptr(pointer, key))
                )
            )
            return None
        result: dict[str, frozenset[str]] = {}
        for prop, deps in as_json_dict(raw).items():
            if not isinstance(deps, MutableSequence) or not all(isinstance(s, str) for s in deps):
                errors.append(
                    SchemaValidationError(
                        f"{key}[{prop!r}] must be an array of strings.",
                        location=loc(source_id, ptr(pointer, key, prop)),
                    )
                )
            else:
                # The `all(isinstance(s, str) for s in deps)` guard above ensures every element
                # is a str; the isinstance filter below is redundant but satisfies the type checker.
                result[prop] = frozenset(x for x in deps if isinstance(x, str))
        return result

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
        if isinstance(value, MutableSequence):
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
        if not isinstance(raw, MutableSequence):
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
        if not isinstance(raw, Mapping):
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
