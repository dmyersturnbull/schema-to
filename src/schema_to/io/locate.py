"""Finding where a JSON Pointer points in a document's raw text.

Diagnostics are raised far from the raw text — by a resolver or a generator working on a CST —
so they name a node by its JSON Pointer.
A person reading one wants a line and a column,
so the pipeline fills those in afterward from the text the document was read from.

The decoders we use do not report positions,
so this re-scans the text along the pointer's path.
For JSON that scan is exact.
For YAML it understands block mappings and sequences — the way schemas are written by hand —
and stops at a flow collection (`{…}` / `[…]`) or anything else it does not follow.
Either way, a segment that cannot be followed yields the position of the deepest node that could,
which still points into the right neighbourhood.
"""

import json
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from schema_to.errors import SourceLocation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from schema_to.io.media_type import MediaType
    from schema_to.io.source import RawDoc

__all__ = ["DocumentLocator", "TextPosition", "locate", "split_doc_id"]


@dataclass(frozen=True, slots=True)
class TextPosition:
    """A 1-based line and column in a text."""

    line: int
    column: int


def split_doc_id(doc_id: str, pointer: str | None = None) -> tuple[str, str]:
    """Split a document ID into the ID of the file it lives in and a pointer within that file.

    A schema carved out of a larger file has an ID like `…/catalog.yaml#/thing`,
    and a pointer relative to `thing`;
    this joins the two into the pointer the file itself would use (`/thing/properties/x`).
    """
    base, sep, fragment = doc_id.partition("#")
    if sep and (not fragment or fragment.startswith("/")):
        return base, fragment + (pointer or "")
    return doc_id, pointer or ""


def locate(content: str | bytes, media_type: MediaType, pointer: str) -> TextPosition | None:
    """Return the position of the node `pointer` names in `content`, or of its deepest ancestor found."""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    segments = _segments(pointer)
    if media_type.subtype.endswith("json"):
        return _offset_to_position(text, _JsonScanner(text).find(segments))
    return _YamlScanner.of(text).find(segments)


@dataclass(frozen=True, slots=True)
class DocumentLocator:
    """Fills in the line and column of a `SourceLocation` from the documents a run read.

    Attributes:
        docs: Raw documents, by `doc_id`.
    """

    docs: Mapping[str, RawDoc]

    def fill(self, location: SourceLocation) -> SourceLocation:
        """Return `location` with its line and column set, if it lacks them and they can be found."""
        if location.line is not None:
            return location
        file_id, pointer = split_doc_id(location.doc_id, location.json_pointer)
        doc = self.docs.get(file_id)
        if doc is None:
            return location
        position = locate(doc.content, doc.media_type, pointer)
        if position is None:
            return location
        return replace(location, line=position.line, column=position.column)


def _segments(pointer: str) -> Sequence[str]:
    if not pointer:
        return []
    return [s.replace("~1", "/").replace("~0", "~") for s in pointer.removeprefix("/").split("/")]


def _offset_to_position(text: str, offset: int | None) -> TextPosition | None:
    if offset is None:
        return None
    line_start = text.rfind("\n", 0, offset) + 1
    return TextPosition(text.count("\n", 0, offset) + 1, offset - line_start + 1)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

_JSON_WS = re.compile(r"[ \t\n\r]*")
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_JSON_SCALAR = re.compile(r"[^,\]}\s]*")


@dataclass(frozen=True, slots=True)
class _JsonScanner:
    text: str

    def find(self, segments: Sequence[str]) -> int | None:
        """Return the offset of the node `segments` leads to, or of the deepest one found."""
        value = self._ws(0)
        if value >= len(self.text):
            return None
        found = value
        # On malformed text, the deepest node found so far is the best answer.
        with suppress(ValueError):
            for segment in segments:
                child = self._child(value, segment)
                if child is None:
                    break
                found, value = child
        return found

    def _child(self, start: int, segment: str) -> tuple[int, int] | None:
        """Return `(reported offset, value offset)` of a child, or `None` if it is absent."""
        if self.text.startswith("{", start):
            return self._member(start, segment)
        if self.text.startswith("[", start) and segment.isdigit():
            return self._element(start, int(segment))
        return None

    def _member(self, start: int, name: str) -> tuple[int, int] | None:
        i = self._ws(start + 1)
        while self.text.startswith('"', i):
            key_start = i
            key, i = _scan_string(self.text, i)
            i = self._ws(i)
            if not self.text.startswith(":", i):
                return None
            i = self._ws(i + 1)
            if key == name:
                return key_start, i
            i = self._next(self._skip(i))
            if i is None:
                return None
        return None

    def _element(self, start: int, index: int) -> tuple[int, int] | None:
        i: int | None = self._ws(start + 1)
        for _ in range(index):
            if i is None or self.text.startswith("]", i):
                return None
            i = self._next(self._skip(i))
        if i is None or self.text.startswith("]", i):
            return None
        return i, i

    def _next(self, end: int) -> int | None:
        """Move past the comma after a value, or return `None` at the end of its container."""
        i = self._ws(end)
        return self._ws(i + 1) if self.text.startswith(",", i) else None

    def _skip(self, start: int) -> int:
        """Return the offset just past the value starting at `start`."""
        if self.text.startswith('"', start):
            return _scan_string(self.text, start)[1]
        if self.text.startswith(("{", "["), start):
            return self._skip_container(start)
        match = _JSON_SCALAR.match(self.text, start)
        return match.end() if match else start

    def _skip_container(self, start: int) -> int:
        depth, i = 0, start
        while i < len(self.text):
            c = self.text[i]
            if c == '"':
                i = _scan_string(self.text, i)[1]
                continue
            if c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        msg = "Unterminated container"
        raise ValueError(msg)

    def _ws(self, i: int) -> int:
        match = _JSON_WS.match(self.text, i)
        return match.end() if match else i


def _scan_string(text: str, start: int) -> tuple[str, int]:
    """Decode the JSON string literal at `start`, returning it and the offset just past it.

    Raises:
        ValueError: If there is no well-formed string literal at `start`.
    """
    match = _JSON_STRING.match(text, start)
    if match is None:
        msg = f"No string literal at offset {start}"
        raise ValueError(msg)
    value = json.loads(match.group())
    if not isinstance(value, str):
        raise TypeError(value)
    return value, match.end()


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

_YAML_PLAIN_KEY = re.compile(r"(?P<key>[^#'\"\s][^#]*?)\s*:(?:\s|$)")


@dataclass(frozen=True, slots=True)
class _YamlLine:
    """A line that holds content, with its indentation split off.

    `indent` is 0-based, so the content starts at column `indent + 1`.
    """

    number: int
    indent: int
    text: str

    @property
    def position(self) -> TextPosition:
        return TextPosition(self.number, self.indent + 1)

    @property
    def is_item(self) -> bool:
        return self.text == "-" or self.text.startswith("- ")

    def item_content(self) -> _YamlLine | None:
        """The content after a sequence item's `- `, as a line of its own; `None` if it has none."""
        rest = self.text[1:]
        content = rest.lstrip(" ")
        if not content or content.startswith("#"):
            return None
        return _YamlLine(self.number, self.indent + 1 + len(rest) - len(content), content)

    def key(self) -> str | None:
        """The mapping key this line starts with, unquoted; `None` if it does not start with one."""
        if self.text.startswith(('"', "'")):
            return self._quoted_key()
        match = _YAML_PLAIN_KEY.match(self.text)
        return match.group("key") if match else None

    def _quoted_key(self) -> str | None:
        quote = self.text[0]
        if quote == '"':
            try:
                key, end = _scan_string(self.text, 0)
            except ValueError:
                return None
        else:
            match = re.match(r"'((?:[^']|'')*)'", self.text)
            if match is None:
                return None
            key, end = match.group(1).replace("''", "'"), match.end()
        return key if self.text[end:].lstrip(" ").startswith(":") else None


@dataclass(frozen=True, slots=True)
class _YamlScanner:
    lines: Sequence[_YamlLine]

    @classmethod
    def of(cls, text: str) -> _YamlScanner:
        lines = []
        for number, raw in enumerate(text.splitlines(), start=1):
            content = raw.lstrip(" ")
            if not content or content.startswith(("#", "---", "...", "%")):
                continue
            lines.append(_YamlLine(number, len(raw) - len(content), content.rstrip()))
        return cls(lines)

    def find(self, segments: Sequence[str]) -> TextPosition | None:
        """Return the position of the node `segments` leads to, or of the deepest one found."""
        if not self.lines:
            return None
        found, region = self.lines[0], self.lines
        for segment in segments:
            child = _yaml_child(region, segment)
            if child is None:
                break
            found, region = child
        return found.position


def _yaml_child(
    region: Sequence[_YamlLine], segment: str
) -> tuple[_YamlLine, Sequence[_YamlLine]] | None:
    """Return the line a child starts on and the lines of its value; `None` if it is not found."""
    if not region:
        return None
    if region[0].is_item:
        return _yaml_item(region, segment)
    return _yaml_member(region, segment)


def _yaml_member(
    region: Sequence[_YamlLine], name: str
) -> tuple[_YamlLine, Sequence[_YamlLine]] | None:
    indent = region[0].indent
    for k, line in enumerate(region):
        if line.indent == indent and line.key() == name:
            end = k + 1
            while end < len(region) and (
                region[end].indent > indent
                or (region[end].indent == indent and region[end].is_item)
            ):
                end += 1
            return line, region[k + 1 : end]
    return None


def _yaml_item(
    region: Sequence[_YamlLine], segment: str
) -> tuple[_YamlLine, Sequence[_YamlLine]] | None:
    indent = region[0].indent
    starts = [k for k, line in enumerate(region) if line.indent == indent and line.is_item]
    if not segment.isdigit() or int(segment) >= len(starts):
        return None
    index = int(segment)
    start = starts[index]
    end = starts[index + 1] if index + 1 < len(starts) else len(region)
    content = region[start].item_content()
    body = region[start + 1 : end]
    if content is None:
        return region[start], body
    return content, [content, *body]
