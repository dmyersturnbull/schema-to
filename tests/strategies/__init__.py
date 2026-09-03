"""Hypothesis strategies for JSON Schema and OpenAPI documents.

Every strategy produces a value that the corresponding parser accepts without errors
and that the corresponding serializer round-trips faithfully.

Modules:
    json_schema: Any JSON Schema 2020-12 value the CST can hold.
    openapi: Any OpenAPI 3.1 document the CST can hold.
    restricted: Deliberately narrowed schemas, for generators whose assertions
        need a predictable shape.  Each says in its docstring what it leaves out
        and which targeted tests cover the remainder.
"""
