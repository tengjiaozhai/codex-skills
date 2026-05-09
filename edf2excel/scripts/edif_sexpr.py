"""EDIF S-expression parser with source locations.

The full exporter needs a loss-light representation of EDIF rather than the
regex slices used by the compare importer. This parser keeps every list node,
atom order, line/column, and a stable path based on list item positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


class EdifParseError(ValueError):
    """Raised when an EDIF file is not a balanced S-expression document."""


@dataclass(slots=True)
class EdifAtom:
    value: str
    raw: str
    line: int
    column: int
    kind: str = "symbol"


EdifItem = "EdifAtom | EdifNode"


@dataclass(slots=True)
class EdifNode:
    items: list[EdifAtom | "EdifNode"]
    line: int
    column: int
    source: Path | None = None
    parent: "EdifNode | None" = field(default=None, repr=False)
    child_index: int = 0

    @property
    def head(self) -> str:
        if self.items and isinstance(self.items[0], EdifAtom):
            return self.items[0].value
        return ""

    @property
    def path(self) -> str:
        segment = f"{self.child_index}:{self.head or '<list>'}"
        if self.parent is None:
            return f"/{segment}"
        return f"{self.parent.path}/{segment}"

    def atom_items(self) -> list[EdifAtom]:
        return [item for item in self.items if isinstance(item, EdifAtom)]

    def atom_value(self, index: int, default: str = "") -> str:
        if 0 <= index < len(self.items) and isinstance(self.items[index], EdifAtom):
            return self.items[index].value
        return default

    def child_nodes(self, head: str | None = None) -> list["EdifNode"]:
        children = [item for item in self.items if isinstance(item, EdifNode)]
        if head is None:
            return children
        folded = head.casefold()
        return [child for child in children if child.head.casefold() == folded]

    def find_first(self, head: str) -> "EdifNode | None":
        folded = head.casefold()
        if self.head.casefold() == folded:
            return self
        for child in self.child_nodes():
            found = child.find_first(head)
            if found is not None:
                return found
        return None

    def walk(self) -> Iterable["EdifNode"]:
        yield self
        for child in self.child_nodes():
            yield from child.walk()


@dataclass(slots=True)
class _Token:
    kind: str
    value: str
    raw: str
    line: int
    column: int


def _advance_position(text: str, line: int, column: int) -> tuple[int, int]:
    for char in text:
        if char == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return line, column


def _tokenize(text: str, source: Path) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    line = 1
    column = 1

    while i < len(text):
        char = text[i]

        if char.isspace():
            line, column = _advance_position(char, line, column)
            i += 1
            continue

        if char == ";":
            while i < len(text) and text[i] != "\n":
                i += 1
                column += 1
            continue

        token_line = line
        token_column = column

        if char in "()":
            tokens.append(_Token(char, char, char, token_line, token_column))
            i += 1
            column += 1
            continue

        if char == '"':
            raw_chars = ['"']
            value_chars: list[str] = []
            i += 1
            column += 1
            closed = False
            while i < len(text):
                current = text[i]
                raw_chars.append(current)
                if current == "\\":
                    if i + 1 >= len(text):
                        break
                    nxt = text[i + 1]
                    raw_chars.append(nxt)
                    value_chars.append(nxt)
                    line, column = _advance_position(current + nxt, line, column)
                    i += 2
                    continue
                if current == '"':
                    line, column = _advance_position(current, line, column)
                    i += 1
                    closed = True
                    break
                value_chars.append(current)
                line, column = _advance_position(current, line, column)
                i += 1
            if not closed:
                raise EdifParseError(
                    f"{source}:{token_line}:{token_column}: unterminated string"
                )
            tokens.append(
                _Token(
                    "string",
                    "".join(value_chars),
                    "".join(raw_chars),
                    token_line,
                    token_column,
                )
            )
            continue

        if char == "|":
            raw_chars = ["|"]
            value_chars: list[str] = []
            i += 1
            column += 1
            closed = False
            while i < len(text):
                current = text[i]
                raw_chars.append(current)
                line, column = _advance_position(current, line, column)
                i += 1
                if current == "|":
                    closed = True
                    break
                value_chars.append(current)
            if not closed:
                raise EdifParseError(
                    f"{source}:{token_line}:{token_column}: unterminated |name|"
                )
            tokens.append(
                _Token(
                    "quoted_symbol",
                    "".join(value_chars),
                    "".join(raw_chars),
                    token_line,
                    token_column,
                )
            )
            continue

        start = i
        while i < len(text):
            current = text[i]
            if current.isspace() or current in "();":
                break
            i += 1
            column += 1
        raw = text[start:i]
        tokens.append(_Token("symbol", raw, raw, token_line, token_column))

    return tokens


def parse_edif_sexpr(path: Path) -> EdifNode:
    """Parse an EDIF file into a single top-level :class:`EdifNode`."""

    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    tokens = _tokenize(text, source)
    stack: list[EdifNode] = []
    roots: list[EdifNode] = []

    for token in tokens:
        if token.kind == "(":
            child_index = len(stack[-1].items) if stack else len(roots)
            node = EdifNode(
                items=[],
                line=token.line,
                column=token.column,
                source=source,
                parent=stack[-1] if stack else None,
                child_index=child_index,
            )
            if stack:
                stack[-1].items.append(node)
            else:
                roots.append(node)
            stack.append(node)
            continue

        if token.kind == ")":
            if not stack:
                raise EdifParseError(
                    f"{source}:{token.line}:{token.column}: unmatched ')'"
                )
            stack.pop()
            continue

        if not stack:
            raise EdifParseError(
                f"{source}:{token.line}:{token.column}: atom outside list"
            )
        stack[-1].items.append(
            EdifAtom(
                value=token.value,
                raw=token.raw,
                line=token.line,
                column=token.column,
                kind=token.kind,
            )
        )

    if stack:
        node = stack[-1]
        raise EdifParseError(
            f"{source}:{node.line}:{node.column}: unterminated list"
        )
    if len(roots) != 1:
        raise EdifParseError(f"{source}: expected exactly one top-level list")
    return roots[0]
