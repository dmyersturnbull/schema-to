"""JSON Schema 2020-12 document parser.

Converts a `RawDoc` (JSON or YAML bytes) into a `JsonSchemaDocument` CST.
The parser is **non-resolving**: `$ref` and `$dynamicRef` values are stored as
raw URI strings.  Pass the result to a `RefResolver` stage to inline them.

Errors are accumulated so that a single parse call returns the complete set of
diagnostics rather than stopping at the first fault.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from schema_to import JsonSchemaRawDoc
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
from schema_to.parse._utils import (
    as_json_dict,
    as_json_list,
    decode_raw_doc,
    int_field,
    num_field,
    ptr,
    str_field,
)
from schema_to.pipeline import DocParser
from schema_to.result import Err, Ok, Result

if TYPE_CHECKING:
    from schema_to.core import JsonValue

__all__ = ["JsonSchemaParser"]

loc = SourceLocation


class JsonSchemaParser(DocParser[JsonSchemaRawDoc, JsonSchemaDocument]):
    """Parses JSON or YAML bytes into a `JsonSchemaDocument` CST.

    The parser is stateless: a single instance may be reused across documents.
    """

    def accepts(self, doc: JsonSchemaRawDoc) -> bool:
        return isinstance(doc, JsonSchemaRawDoc)

    def apply(self, input: JsonSchemaRawDoc) -> Result[JsonSchemaDocument]:
        try:
            raw = decode_raw_doc(input)
        except TranspilationError as exc:
            return Err((exc,))
        return self._build_document(raw, document=input)

    def _build_document(
        self, data: JsonValue, *, document: JsonSchemaRawDoc
    ) -> Result[JsonSchemaDocument]:
        root_r = self._build_schema(data, source_id=document.source_id, pointer="")
        if isinstance(root_r, Err):
            return root_r
        return Ok(
            JsonSchemaDocument(
                root=root_r.value,
                source_id=document.source_id,
                display_name=document.display_name,
                source_ref=SourceRef(document.source_id, ""),
            )
        )

    def _build_schema(self, data: JsonValue, *, source_id: str, pointer: str) -> Result[JsonSchema]:
        if isinstance(data, bool):
            return Ok(BooleanSchema(value=data, source_ref=SourceRef(source_id, pointer)))
        if isinstance(data, dict):
            # ty treats Ok[T] as invariant; cast asserts the safe covariant narrowing:
            # Ok[ObjectSchema] is structurally ≤ Result[JsonSchema] at runtime.
            return cast(
                "Result[JsonSchema]",
                self._build_object_schema(
                    cast("dict[str, JsonValue]", data), source_id=source_id, pointer=pointer
                ),
            )
        return Err(
            (
                ParseError(
                    f"Schema must be `true`, `false`, or an object; got {type(data).__name__!r}.",
                    location=loc(source_id, pointer),
                ),
            )
        )

    def _build_object_schema(  # noqa: PLR0914 # ObjectSchema has 30+ fields; sub-builders already extracted
        self, data: dict[str, JsonValue], *, source_id: str, pointer: str
    ) -> Result[ObjectSchema]:
        errors: list[TranspilationError] = []

        # -- Core vocabulary -----------------------------------------------
        defs = self._build_schema_map(
            data, "$defs", source_id=source_id, pointer=pointer, errors=errors
        )
        vocabulary = self._parse_vocabulary(
            data, source_id=source_id, pointer=pointer, errors=errors
        )

        # -- Metadata vocabulary -------------------------------------------
        examples = self._parse_examples(data, source_id=source_id, pointer=pointer, errors=errors)

        # -- Validation vocabulary -----------------------------------------
        schema_type: SchemaType | None = None
        if "type" in data:
            r = self._parse_schema_type(data["type"], location=loc(source_id, ptr(pointer, "type")))
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                schema_type = r.value

        enum_val = self._parse_enum(data, source_id=source_id, pointer=pointer, errors=errors)

        # -- Numeric / string constraint validation ------------------------
        self._validate_numeric_constraints(
            data, source_id=source_id, pointer=pointer, errors=errors
        )
        self._validate_string_constraints(data, source_id=source_id, pointer=pointer, errors=errors)

        # -- Array keywords ------------------------------------------------
        prefix_items = self._build_schema_list(
            data, "prefixItems", source_id=source_id, pointer=pointer, errors=errors
        )
        items = self._build_optional_schema(
            data, "items", source_id=source_id, pointer=pointer, errors=errors
        )
        contains = self._build_optional_schema(
            data, "contains", source_id=source_id, pointer=pointer, errors=errors
        )

        # -- Object keywords -----------------------------------------------
        properties = self._build_schema_map(
            data, "properties", source_id=source_id, pointer=pointer, errors=errors
        )
        pattern_properties = self._build_schema_map(
            data, "patternProperties", source_id=source_id, pointer=pointer, errors=errors
        )
        additional_properties = self._build_optional_schema(
            data, "additionalProperties", source_id=source_id, pointer=pointer, errors=errors
        )
        property_names = self._build_optional_schema(
            data, "propertyNames", source_id=source_id, pointer=pointer, errors=errors
        )
        dependent_schemas = self._build_schema_map(
            data, "dependentSchemas", source_id=source_id, pointer=pointer, errors=errors
        )
        required = self._parse_required(data, source_id=source_id, pointer=pointer, errors=errors)
        dependent_required = self._parse_dependent_required(
            data, source_id=source_id, pointer=pointer, errors=errors
        )

        # -- Applicator vocabulary -----------------------------------------
        all_of = self._build_schema_list(
            data, "allOf", source_id=source_id, pointer=pointer, errors=errors
        )
        any_of = self._build_schema_list(
            data, "anyOf", source_id=source_id, pointer=pointer, errors=errors
        )
        one_of = self._build_schema_list(
            data, "oneOf", source_id=source_id, pointer=pointer, errors=errors
        )
        not_ = self._build_optional_schema(
            data, "not", source_id=source_id, pointer=pointer, errors=errors
        )
        if_ = self._build_optional_schema(
            data, "if", source_id=source_id, pointer=pointer, errors=errors
        )
        then = self._build_optional_schema(
            data, "then", source_id=source_id, pointer=pointer, errors=errors
        )
        else_ = self._build_optional_schema(
            data, "else", source_id=source_id, pointer=pointer, errors=errors
        )

        # -- Unevaluated vocabulary ----------------------------------------
        unevaluated_items = self._build_optional_schema(
            data, "unevaluatedItems", source_id=source_id, pointer=pointer, errors=errors
        )
        unevaluated_properties = self._build_optional_schema(
            data, "unevaluatedProperties", source_id=source_id, pointer=pointer, errors=errors
        )

        # -- Content vocabulary --------------------------------------------
        content_schema = self._build_optional_schema(
            data, "contentSchema", source_id=source_id, pointer=pointer, errors=errors
        )

        if errors:
            return Err(tuple(errors))

        return Ok(
            ObjectSchema(
                # Core
                id=str_field(data, "$id"),
                schema=str_field(data, "$schema"),
                anchor=str_field(data, "$anchor"),
                dynamic_anchor=str_field(data, "$dynamicAnchor"),
                ref=str_field(data, "$ref"),
                dynamic_ref=str_field(data, "$dynamicRef"),
                defs=defs,
                comment=str_field(data, "$comment"),
                vocabulary=vocabulary,
                # Metadata
                title=str_field(data, "title"),
                description=str_field(data, "description"),
                default=DefaultValue(data["default"]) if "default" in data else None,
                deprecated=bool(data.get("deprecated")),
                read_only=bool(data.get("readOnly")),
                write_only=bool(data.get("writeOnly")),
                examples=examples,
                # Validation
                type=schema_type,
                enum=enum_val,
                const=ConstValue(data["const"]) if "const" in data else None,
                # Numeric
                multiple_of=num_field(data, "multipleOf"),
                maximum=num_field(data, "maximum"),
                exclusive_maximum=num_field(data, "exclusiveMaximum"),
                minimum=num_field(data, "minimum"),
                exclusive_minimum=num_field(data, "exclusiveMinimum"),
                # String
                max_length=int_field(data, "maxLength"),
                min_length=int_field(data, "minLength"),
                pattern=str_field(data, "pattern"),
                # Array
                prefix_items=prefix_items,
                items=items,
                contains=contains,
                min_contains=int_field(data, "minContains"),
                max_contains=int_field(data, "maxContains"),
                min_items=int_field(data, "minItems"),
                max_items=int_field(data, "maxItems"),
                unique_items=bool(data.get("uniqueItems")),
                # Object
                properties=properties,
                pattern_properties=pattern_properties,
                additional_properties=additional_properties,
                property_names=property_names,
                required=required,
                dependent_required=dependent_required,
                dependent_schemas=dependent_schemas,
                min_properties=int_field(data, "minProperties"),
                max_properties=int_field(data, "maxProperties"),
                # Applicator
                all_of=all_of,
                any_of=any_of,
                one_of=one_of,
                not_=not_,
                if_=if_,
                then=then,
                else_=else_,
                # Unevaluated
                unevaluated_items=unevaluated_items,
                unevaluated_properties=unevaluated_properties,
                # Content
                content_encoding=str_field(data, "contentEncoding"),
                content_media_type=str_field(data, "contentMediaType"),
                content_schema=content_schema,
                # Format
                format=str_field(data, "format"),
                # Extensions and provenance
                extensions={k: v for k, v in data.items() if k.startswith("x-")},
                source_ref=SourceRef(source_id, pointer),
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

    def _parse_examples(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[JsonValue] | None:
        if "examples" not in data:
            return None
        raw_ex = data["examples"]
        if not isinstance(raw_ex, list):
            errors.append(
                SchemaValidationError(
                    "examples must be an array.", location=loc(source_id, ptr(pointer, "examples"))
                )
            )
            return None
        return as_json_list(raw_ex)

    def _parse_enum(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> list[JsonValue] | None:
        if "enum" not in data:
            return None
        raw_enum = data["enum"]
        if not isinstance(raw_enum, list):
            errors.append(
                SchemaValidationError(
                    "enum must be an array.", location=loc(source_id, ptr(pointer, "enum"))
                )
            )
            return None
        return as_json_list(raw_enum)

    def _validate_numeric_constraints(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> None:
        for key in ("multipleOf", "maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum"):
            val = data.get(key)
            if val is not None and not isinstance(val, (int, float)):
                errors.append(
                    SchemaValidationError(
                        f"{key} must be a number.", location=loc(source_id, ptr(pointer, key))
                    )
                )

    def _validate_string_constraints(
        self,
        data: dict[str, JsonValue],
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> None:
        for key in ("maxLength", "minLength"):
            val = data.get(key)
            if val is not None and (not isinstance(val, int) or val < 0):
                errors.append(
                    SchemaValidationError(
                        f"{key} must be a non-negative integer.",
                        location=loc(source_id, ptr(pointer, key)),
                    )
                )

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
