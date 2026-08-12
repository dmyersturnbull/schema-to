"""Recursive-descent parser compiling a ``where`` expression to a SQL predicate.

The grammar::

    expr       := or_expr
    or_expr    := and_expr ( "or" and_expr )*
    and_expr   := not_expr ( "and" not_expr )*
    not_expr   := "not" not_expr | atom
    atom       := "(" expr ")" | comparison
    comparison := path OP value
    OP         := "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "in" | "like"
    path       := IDENT ( "." IDENT )*      # dotted: nested keys address JSON
    value      := number | string | "true" | "false" | "null"
                  | "[" value ( "," value )* "]"
"""

import re

from psycopg import sql

from query_dsl._compose import OPERATORS, Params, QueryError, Value, column_ref

__all__ = ["parse_where"]

_TOKEN = re.compile(
    r"\s*(?:(?P<lparen>\()|(?P<rparen>\))|(?P<lbracket>\[)|(?P<rbracket>\])"
    r"|(?P<comma>,)|(?P<string>'(?:[^']|'')*')|(?P<number>-?\d+(?:\.\d+)?)"
    r"|(?P<word>[A-Za-z_][A-Za-z0-9_.]*))"
)

type _Token = tuple[str, str]


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        match = _TOKEN.match(text, pos)
        if match is None or match.lastgroup is None:
            msg = f"Invalid character in where expression at offset {pos}."
            raise QueryError(msg)
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        pos = match.end()
    return tokens


class _WhereParser:
    """Compiles a tokenised where expression into a ``psycopg.sql`` predicate."""

    def __init__(self, text: str, json_columns: frozenset[str], params: Params) -> None:
        self._tokens = _tokenize(text)
        self._pos = 0
        self._json = json_columns
        self._params = params

    def parse(self) -> sql.Composable:
        node = self._or_expr()
        if self._pos != len(self._tokens):
            msg = "Trailing tokens in where expression."
            raise QueryError(msg)
        return node

    def _peek(self) -> _Token | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _next(self) -> _Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _is_keyword(self, word: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == "word" and token[1].lower() == word

    def _or_expr(self) -> sql.Composable:
        parts = [self._and_expr()]
        while self._is_keyword("or"):
            self._next()
            parts.append(self._and_expr())
        if len(parts) == 1:
            return parts[0]
        return sql.SQL("({})").format(sql.SQL(" OR ").join(parts))

    def _and_expr(self) -> sql.Composable:
        parts = [self._not_expr()]
        while self._is_keyword("and"):
            self._next()
            parts.append(self._not_expr())
        if len(parts) == 1:
            return parts[0]
        return sql.SQL("({})").format(sql.SQL(" AND ").join(parts))

    def _not_expr(self) -> sql.Composable:
        if self._is_keyword("not"):
            self._next()
            return sql.SQL("NOT ({})").format(self._not_expr())
        return self._atom()

    def _atom(self) -> sql.Composable:
        token = self._peek()
        if token is not None and token[0] == "lparen":
            self._next()
            node = self._or_expr()
            self._expect("rparen")
            return node
        return self._comparison()

    def _comparison(self) -> sql.Composable:
        path = self._expect("word")
        op = self._expect("word").lower()
        if op not in OPERATORS and op != "in":
            msg = f"Unknown operator {op!r} in where expression."
            raise QueryError(msg)
        col = column_ref(path, self._json, self._params)
        value = self._value()
        if op == "in":
            members = value if isinstance(value, list) else [value]
            return sql.SQL("{} = ANY({})").format(col, self._params.add(members))
        return sql.SQL("{} {} {}").format(col, OPERATORS[op], self._params.add(value))

    def _value(self) -> Value:
        kind, text = self._next()
        if kind == "string":
            return text[1:-1].replace("''", "'")
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "lbracket":
            return self._list()
        if kind == "word" and text.lower() in _LITERALS:
            return _LITERALS[text.lower()]
        msg = f"Expected a value in where expression, got {text!r}."
        raise QueryError(msg)

    def _list(self) -> list[Value]:
        items: list[Value] = []
        if self._at("rbracket"):
            self._next()
            return items
        items.append(self._value())
        while self._at("comma"):
            self._next()
            items.append(self._value())
        self._expect("rbracket")
        return items

    def _at(self, kind: str) -> bool:
        token = self._peek()
        return token is not None and token[0] == kind

    def _expect(self, kind: str) -> str:
        token = self._peek()
        if token is None or token[0] != kind:
            msg = f"Expected {kind} in where expression."
            raise QueryError(msg)
        self._next()
        return token[1]


_LITERALS: dict[str, bool | None] = {"true": True, "false": False, "null": None}


def parse_where(where: str, json_columns: frozenset[str], params: Params) -> sql.Composable:
    """Compile a ``where`` expression into a parameterised SQL predicate."""
    return _WhereParser(where, json_columns, params).parse()
