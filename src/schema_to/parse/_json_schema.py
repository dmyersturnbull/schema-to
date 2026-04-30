"""JSON Schema 2020-12 document parser.

Converts a `RawDocument` (JSON or YAML bytes) into a `JsonSchemaDocument` CST.
The parser is **non-resolving**: `$ref` and `$dynamicRef` values are stored as
raw URI strings.  Pass the result to a `RefResolver` stage to inline them.

Errors are accumulated across all vocabulary groups so that a single parse call
returns the complete set of diagnostics rather than stopping at the first fault.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from schema_to._errors import ParseError, SchemaValidationError, TranspilationError
from schema_to._pipeline import DocumentParser
from schema_to._result import Err, Ok, Result
from schema_to.cst._base import SourceRef
from schema_to.parse._utils import _escape, _extract, _loc, _ptr  # noqa: F401
from schema_to.cst._json_schema import (
    ConstValue,
    ApplicatorKeywords,
    ArrayKeywords,
    BooleanSchema,
    ContentKeywords,
    CoreKeywords,
    DefaultValue,
    FormatKeyword,
    JsonSchema,
    JsonSchemaDocument,
    JsonSchemaType,
    MetadataKeywords,
    NumericKeywords,
    ObjectKeywords,
    ObjectSchema,
    SchemaType,
    StringKeywords,
    UnevaluatedKeywords,
    ValidationKeywords,
)
from schema_to.io._source import RawDocument

__all__ = ["JsonSchemaParser"]

# Media-type strings accepted by this parser.
_SUPPORTED_ESSENCES = frozenset({"application/json", "application/yaml", "text/yaml"})



# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class JsonSchemaParser(DocumentParser[JsonSchemaDocument]):
    """Parses JSON or YAML bytes into a `JsonSchemaDocument` CST.

    The parser is stateless: a single instance may be reused across documents.
    """

    # -- DocumentParser interface ------------------------------------------

    def supports(self, document: RawDocument) -> bool:
        return document.media_type.essence in _SUPPORTED_ESSENCES

    def apply(self, input: RawDocument) -> Result[JsonSchemaDocument]:
        raw = self._decode(input)
        if isinstance(raw, Err):
            return raw
        return self._build_document(raw.value, document=input)

    # -- Decoding ----------------------------------------------------------

    def _decode(self, document: RawDocument) -> Result[Any]:
        essence = document.media_type.essence
        try:
            if essence == "application/json":
                return Ok(json.loads(document.content))
            if essence in {"application/yaml", "text/yaml"}:
                import yaml12  # noqa: PLC0415

                return Ok(yaml12.parse_yaml(document.content.decode()))
        except json.JSONDecodeError as exc:
            return Err(
                (
                    ParseError(
                        str(exc),
                        location=SourceLocation(
                            document.source_id,
                            line=exc.lineno,
                            column=exc.colno,
                        ),
                        cause=exc,
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return Err(
                (ParseError(str(exc), location=_loc(document.source_id, ""), cause=exc),)
            )
        return Err(
            (
                ParseError(
                    f"Unsupported media type for JSON Schema: {essence!r}",
                    location=_loc(document.source_id, ""),
                ),
            )
        )

    # -- Document root -----------------------------------------------------

    def _build_document(
        self,
        data: Any,
        *,
        document: RawDocument,
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

    # -- Schema dispatch ---------------------------------------------------

    def _build_schema(
        self,
        data: Any,
        *,
        source_id: str,
        pointer: str,
    ) -> Result[JsonSchema]:
        # bool must be checked before dict: bool is a subclass of int, not dict,
        # but a defensive ordering avoids surprises.
        if isinstance(data, bool):
            return Ok(BooleanSchema(value=data, source_ref=SourceRef(source_id, pointer)))
        if isinstance(data, dict):
            return self._build_object_schema(data, source_id=source_id, pointer=pointer)
        return Err(
            (
                ParseError(
                    f"Schema must be `true`, `false`, or an object; got {type(data).__name__!r}.",
                    location=_loc(source_id, pointer),
                ),
            )
        )

    # -- Object schema -----------------------------------------------------

    def _build_object_schema(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ObjectSchema]:
        errors: list[TranspilationError] = []

        core = _extract(self._build_core(data, source_id=source_id, pointer=pointer), errors)
        meta = _extract(self._build_metadata(data, source_id=source_id, pointer=pointer), errors)
        validation = _extract(
            self._build_validation(data, source_id=source_id, pointer=pointer), errors
        )
        numeric = _extract(self._build_numeric(data, source_id=source_id, pointer=pointer), errors)
        string = _extract(self._build_string(data, source_id=source_id, pointer=pointer), errors)
        array = _extract(self._build_array(data, source_id=source_id, pointer=pointer), errors)
        obj = _extract(self._build_object(data, source_id=source_id, pointer=pointer), errors)
        applicator = _extract(
            self._build_applicator(data, source_id=source_id, pointer=pointer), errors
        )
        unevaluated = _extract(
            self._build_unevaluated(data, source_id=source_id, pointer=pointer), errors
        )
        content = _extract(self._build_content(data, source_id=source_id, pointer=pointer), errors)
        fmt = _extract(self._build_format(data), errors)
        extensions = {k: v for k, v in data.items() if k.startswith("x-")}

        if errors:
            return Err(tuple(errors))

        # All extractions succeeded; none of the locals can be None here.
        return Ok(
            ObjectSchema(
                core=core,  # type: ignore[arg-type]
                metadata=meta,  # type: ignore[arg-type]
                validation=validation,  # type: ignore[arg-type]
                numeric=numeric,  # type: ignore[arg-type]
                string=string,  # type: ignore[arg-type]
                array=array,  # type: ignore[arg-type]
                object=obj,  # type: ignore[arg-type]
                applicator=applicator,  # type: ignore[arg-type]
                unevaluated=unevaluated,  # type: ignore[arg-type]
                content=content,  # type: ignore[arg-type]
                format_annotation=fmt,  # type: ignore[arg-type]  # noqa: A002
                extensions=extensions,
                source_ref=SourceRef(source_id, pointer),
            )
        )

    # -- Vocabulary builders -----------------------------------------------

    def _build_core(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[CoreKeywords]:
        errors: list[TranspilationError] = []

        defs = self._build_schema_map(
            data, "$defs", source_id=source_id, pointer=pointer, errors=errors
        )
        vocabulary: dict[str, bool] | None = None
        if "$vocabulary" in data:
            raw_vocab = data["$vocabulary"]
            if not isinstance(raw_vocab, dict):
                errors.append(
                    SchemaValidationError(
                        "$vocabulary must be an object.",
                        location=_loc(source_id, _ptr(pointer, "$vocabulary")),
                    )
                )
            else:
                vocabulary = {}
                for uri, required in raw_vocab.items():
                    if not isinstance(required, bool):
                        errors.append(
                            SchemaValidationError(
                                f"$vocabulary value for {uri!r} must be a boolean.",
                                location=_loc(source_id, _ptr(pointer, "$vocabulary", uri)),
                            )
                        )
                    else:
                        vocabulary[uri] = required

        if errors:
            return Err(tuple(errors))

        return Ok(
            CoreKeywords(
                id=data.get("$id"),
                schema=data.get("$schema"),
                anchor=data.get("$anchor"),
                dynamic_anchor=data.get("$dynamicAnchor"),
                ref=data.get("$ref"),
                dynamic_ref=data.get("$dynamicRef"),
                defs=defs,
                comment=data.get("$comment"),
                vocabulary=vocabulary,
            )
        )

    def _build_metadata(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[MetadataKeywords]:
        errors: list[TranspilationError] = []

        examples: list[Any] | None = None
        if "examples" in data:
            raw_ex = data["examples"]
            if not isinstance(raw_ex, list):
                errors.append(
                    SchemaValidationError(
                        "examples must be an array.",
                        location=_loc(source_id, _ptr(pointer, "examples")),
                    )
                )
            else:
                examples = list(raw_ex)

        if errors:
            return Err(tuple(errors))

        default = DefaultValue(data["default"]) if "default" in data else None
        return Ok(
            MetadataKeywords(
                title=data.get("title"),
                description=data.get("description"),
                default=default,
                deprecated=bool(data.get("deprecated", False)),
                read_only=bool(data.get("readOnly", False)),
                write_only=bool(data.get("writeOnly", False)),
                examples=examples,
            )
        )

    def _build_validation(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ValidationKeywords]:
        errors: list[TranspilationError] = []

        schema_type: SchemaType | None = None
        if "type" in data:
            r = self._parse_schema_type(
                data["type"], location=_loc(source_id, _ptr(pointer, "type"))
            )
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                schema_type = r.value

        enum_val: list[Any] | None = None
        if "enum" in data:
            raw_enum = data["enum"]
            if not isinstance(raw_enum, list):
                errors.append(
                    SchemaValidationError(
                        "enum must be an array.",
                        location=_loc(source_id, _ptr(pointer, "enum")),
                    )
                )
            else:
                enum_val = list(raw_enum)

        const = ConstValue(data["const"]) if "const" in data else None

        if errors:
            return Err(tuple(errors))

        return Ok(ValidationKeywords(type=schema_type, enum=enum_val, const=const))

    def _build_numeric(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[NumericKeywords]:
        errors: list[TranspilationError] = []
        for key in ("multipleOf", "maximum", "exclusiveMaximum", "minimum", "exclusiveMinimum"):
            val = data.get(key)
            if val is not None and not isinstance(val, (int, float)):
                errors.append(
                    SchemaValidationError(
                        f"{key} must be a number.",
                        location=_loc(source_id, _ptr(pointer, key)),
                    )
                )
        if errors:
            return Err(tuple(errors))
        return Ok(
            NumericKeywords(
                multiple_of=data.get("multipleOf"),
                maximum=data.get("maximum"),
                exclusive_maximum=data.get("exclusiveMaximum"),
                minimum=data.get("minimum"),
                exclusive_minimum=data.get("exclusiveMinimum"),
            )
        )

    def _build_string(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[StringKeywords]:
        errors: list[TranspilationError] = []
        for key in ("maxLength", "minLength"):
            val = data.get(key)
            if val is not None and (not isinstance(val, int) or val < 0):
                errors.append(
                    SchemaValidationError(
                        f"{key} must be a non-negative integer.",
                        location=_loc(source_id, _ptr(pointer, key)),
                    )
                )
        if errors:
            return Err(tuple(errors))
        return Ok(
            StringKeywords(
                max_length=data.get("maxLength"),
                min_length=data.get("minLength"),
                pattern=data.get("pattern"),
            )
        )

    def _build_array(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ArrayKeywords]:
        errors: list[TranspilationError] = []

        prefix_items = self._build_schema_list(
            data, "prefixItems", source_id=source_id, pointer=pointer, errors=errors
        )
        items = self._build_optional_schema(
            data, "items", source_id=source_id, pointer=pointer, errors=errors
        )
        contains = self._build_optional_schema(
            data, "contains", source_id=source_id, pointer=pointer, errors=errors
        )

        if errors:
            return Err(tuple(errors))

        return Ok(
            ArrayKeywords(
                prefix_items=prefix_items,
                items=items,
                contains=contains,
                min_contains=data.get("minContains"),
                max_contains=data.get("maxContains"),
                min_items=data.get("minItems"),
                max_items=data.get("maxItems"),
                unique_items=bool(data.get("uniqueItems", False)),
            )
        )

    def _build_object(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ObjectKeywords]:
        errors: list[TranspilationError] = []

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

        required: frozenset[str] | None = None
        if "required" in data:
            raw_req = data["required"]
            if not isinstance(raw_req, list) or not all(isinstance(s, str) for s in raw_req):
                errors.append(
                    SchemaValidationError(
                        "required must be an array of strings.",
                        location=_loc(source_id, _ptr(pointer, "required")),
                    )
                )
            else:
                required = frozenset(raw_req)

        dependent_required: dict[str, frozenset[str]] | None = None
        if "dependentRequired" in data:
            raw_dr = data["dependentRequired"]
            if not isinstance(raw_dr, dict):
                errors.append(
                    SchemaValidationError(
                        "dependentRequired must be an object.",
                        location=_loc(source_id, _ptr(pointer, "dependentRequired")),
                    )
                )
            else:
                dependent_required = {}
                for prop, deps in raw_dr.items():
                    if not isinstance(deps, list) or not all(isinstance(s, str) for s in deps):
                        errors.append(
                            SchemaValidationError(
                                f"dependentRequired[{prop!r}] must be an array of strings.",
                                location=_loc(
                                    source_id, _ptr(pointer, "dependentRequired", prop)
                                ),
                            )
                        )
                    else:
                        dependent_required[prop] = frozenset(deps)

        if errors:
            return Err(tuple(errors))

        return Ok(
            ObjectKeywords(
                properties=properties,
                pattern_properties=pattern_properties,
                additional_properties=additional_properties,
                property_names=property_names,
                required=required,
                dependent_required=dependent_required,
                dependent_schemas=dependent_schemas,
                min_properties=data.get("minProperties"),
                max_properties=data.get("maxProperties"),
            )
        )

    def _build_applicator(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ApplicatorKeywords]:
        errors: list[TranspilationError] = []

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

        if errors:
            return Err(tuple(errors))

        return Ok(
            ApplicatorKeywords(
                all_of=all_of,
                any_of=any_of,
                one_of=one_of,
                not_=not_,
                if_=if_,
                then=then,
                else_=else_,
            )
        )

    def _build_unevaluated(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[UnevaluatedKeywords]:
        errors: list[TranspilationError] = []
        unevaluated_items = self._build_optional_schema(
            data, "unevaluatedItems", source_id=source_id, pointer=pointer, errors=errors
        )
        unevaluated_properties = self._build_optional_schema(
            data, "unevaluatedProperties", source_id=source_id, pointer=pointer, errors=errors
        )
        if errors:
            return Err(tuple(errors))
        return Ok(
            UnevaluatedKeywords(
                unevaluated_items=unevaluated_items,
                unevaluated_properties=unevaluated_properties,
            )
        )

    def _build_content(
        self,
        data: dict[str, Any],
        *,
        source_id: str,
        pointer: str,
    ) -> Result[ContentKeywords]:
        errors: list[TranspilationError] = []
        content_schema = self._build_optional_schema(
            data, "contentSchema", source_id=source_id, pointer=pointer, errors=errors
        )
        if errors:
            return Err(tuple(errors))
        return Ok(
            ContentKeywords(
                content_encoding=data.get("contentEncoding"),
                content_media_type=data.get("contentMediaType"),
                content_schema=content_schema,
            )
        )

    def _build_format(self, data: dict[str, Any]) -> Result[FormatKeyword]:
        return Ok(FormatKeyword(format=data.get("format")))

    # -- Reusable sub-builders ---------------------------------------------

    def _parse_schema_type(
        self,
        value: Any,
        *,
        location: SourceLocation,
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
            errors: list[TranspilationError] = []
            for item in value:
                if not isinstance(item, str):
                    errors.append(
                        SchemaValidationError(
                            "type array elements must be strings.", location=location
                        )
                    )
                    continue
                try:
                    types.append(JsonSchemaType(item))
                except ValueError:
                    errors.append(
                        SchemaValidationError(
                            f"Unknown primitive type: {item!r}.", location=location
                        )
                    )
            if errors:
                return Err(tuple(errors))
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
        data: dict[str, Any],
        key: str,
        *,
        source_id: str,
        pointer: str,
        errors: list[TranspilationError],
    ) -> JsonSchema | None:
        if key not in data:
            return None
        r = self._build_schema(
            data[key], source_id=source_id, pointer=_ptr(pointer, key)
        )
        if isinstance(r, Err):
            errors.extend(r.errors)
            return None
        return r.value

    def _build_schema_list(
        self,
        data: dict[str, Any],
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
                    f"{key} must be an array.",
                    location=_loc(source_id, _ptr(pointer, key)),
                )
            )
            return None
        result: list[JsonSchema] = []
        for i, item in enumerate(raw):
            r = self._build_schema(item, source_id=source_id, pointer=_ptr(pointer, key, i))
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                result.append(r.value)
        return result

    def _build_schema_map(
        self,
        data: dict[str, Any],
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
                    f"{key} must be an object.",
                    location=_loc(source_id, _ptr(pointer, key)),
                )
            )
            return None
        result: dict[str, JsonSchema] = {}
        for name, value in raw.items():
            r = self._build_schema(
                value, source_id=source_id, pointer=_ptr(pointer, key, name)
            )
            if isinstance(r, Err):
                errors.extend(r.errors)
            else:
                result[name] = r.value
        return result
