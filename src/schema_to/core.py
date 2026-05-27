from collections.abc import MutableMapping, MutableSequence

type JsonPrimitive = bool | int | float | str | None
type JsonArray = MutableSequence[JsonValue]
type JsonObject = MutableMapping[str, JsonValue]
type JsonValue = JsonPrimitive | JsonArray | JsonObject
