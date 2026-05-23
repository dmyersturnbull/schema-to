type JsonPrimitive = bool | int | float | str | None
type JsonArray = list[JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonValue = JsonPrimitive | JsonArray | JsonObject
