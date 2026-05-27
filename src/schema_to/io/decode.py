from json import JSONDecodeError

from schema_to.io.core import JsonReader, ReadError, JsonLikeReader
from schema_to.io.core import YamlReader

from schema_to import RawDocument, MediaTypes, ParseError, SourceLocation


def decode(document: RawDocument):
    try:
        return JsonLikeReader().read(document.content)
        if document.media_type == MediaTypes.json:
            return JsonReader().read(document.content.decode("utf-8"))
        if document.media_type == MediaTypes.yaml:
            return YamlReader().read(document.content.decode("utf-8"))
    except ReadError as e:
        raise ParseError(str(e), location=SourceLocation(document.source_id, line=e.line, column=e.column)) from e
