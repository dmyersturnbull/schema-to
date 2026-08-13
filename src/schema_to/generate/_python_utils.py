"""Utilities for Python targets."""

from schema_to.ast.python import PythonTypeAnnotation
from schema_to.cst.json_schema import JsonSchemaType

ANY = PythonTypeAnnotation("Any", module="typing")
NONE = PythonTypeAnnotation("None")
STR = PythonTypeAnnotation("str")
INT = PythonTypeAnnotation("int")
FLOAT = PythonTypeAnnotation("float")
BOOL = PythonTypeAnnotation("bool")

PRIMITIVE_MAP: dict[JsonSchemaType, PythonTypeAnnotation] = {
    JsonSchemaType.STRING: STR,
    JsonSchemaType.INTEGER: INT,
    JsonSchemaType.NUMBER: FLOAT,
    JsonSchemaType.BOOLEAN: BOOL,
    JsonSchemaType.NULL: NONE,
}


def nullable(ann: PythonTypeAnnotation) -> PythonTypeAnnotation:
    return PythonTypeAnnotation(ann.name, args=ann.args, module=ann.module, nullable=True)


def literal(*values: object) -> PythonTypeAnnotation:
    args = [PythonTypeAnnotation(repr(v)) for v in values]
    return PythonTypeAnnotation("Literal", args=args, module="typing")
