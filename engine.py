
"""
PlainMath parsing and layout engine.

Fractions use one structural group:

    {a/b}

The braces are visible in PRE-RENDER but invisible in RENDERED.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple, Union


# ============================================================================
# Constants
# ============================================================================

ATOM_CHARS_RE = re.compile(r"[A-Za-z0-9_.]+")
ADDITIVE_OPERATORS = "+-"
MULTIPLICATIVE_OPERATORS = "*/"


# ============================================================================
# Expression nodes
# ============================================================================

@dataclass
class AtomNode:
    text: str
    start: int
    end: int


@dataclass
class TextNode:
    text: str
    start: int
    end: int


@dataclass
class GroupNode:
    inner: "Sequence"
    start: int
    end: int
    left_pos: int
    right_pos: int
    visible: bool


@dataclass
class BinaryNode:
    left: "Term"
    operator: str
    right: "Term"
    start: int
    end: int
    operator_pos: int


@dataclass
class FracNode:
    numerator: "Term"
    denominator: "Term"
    slash_pos: int
    start: int
    end: int
    open_pos: int = -1
    close_pos: int = -1


Term = Union[AtomNode, TextNode, GroupNode, BinaryNode, FracNode]
Sequence = List[Tuple[str, Term]]


# ============================================================================
# Basic helpers
# ============================================================================

def _skip_spaces(s: str, pos: int, end: int) -> int:
    while pos < end and s[pos].isspace():
        pos += 1
    return pos


# ============================================================================
# Parser
# ============================================================================

def parse_line(line: str) -> Sequence:
    if not line:
        return []

    sequence, _ = _parse_additive_expression(line, 0, len(line))
    return sequence


def _parse_additive_expression(
    s: str,
    pos: int,
    end: int,
) -> Tuple[Sequence, int]:

    terms: Sequence = []
    pos = _skip_spaces(s, pos, end)

    if pos >= end:
        return [], pos

    first, pos = _parse_multiplicative_expression(s, pos, end)

    if first is not None:
        terms.append(("", first))

    while pos < end:
        pos = _skip_spaces(s, pos, end)

        if pos >= end or s[pos] == "}":
            break

        if s[pos] not in ADDITIVE_OPERATORS:
            break

        operator = s[pos]
        pos += 1
        after_operator = _skip_spaces(s, pos, end)

        if after_operator >= end:
            terms.append((
                operator,
                TextNode("", after_operator, after_operator),
            ))
            pos = after_operator
            break

        right, new_pos = _parse_multiplicative_expression(
            s, after_operator, end
        )

        if right is None or new_pos <= after_operator:
            terms.append((
                operator,
                TextNode("", after_operator, after_operator),
            ))
            pos = after_operator
            break

        terms.append((operator, right))
        pos = new_pos

    return terms, pos


def _parse_multiplicative_expression(
    s: str,
    pos: int,
    end: int,
) -> Tuple[Term | None, int]:

    pos = _skip_spaces(s, pos, end)

    if pos >= end or s[pos] in ")}":
        return None, pos

    first, pos = _parse_primary(s, pos, end)

    if first is None:
        return None, pos

    current = first

    while pos < end:
        pos = _skip_spaces(s, pos, end)

        if pos >= end or s[pos] in ")}":
            break

        if s[pos] not in MULTIPLICATIVE_OPERATORS:
            break

        operator = s[pos]
        operator_pos = pos
        pos += 1
        after_operator = _skip_spaces(s, pos, end)

        if after_operator >= end:
            empty = TextNode("", after_operator, after_operator)

            if operator == "/":
                current = FracNode(
                    current, empty, operator_pos,
                    current.start, after_operator,
                )
            else:
                current = BinaryNode(
                    current, operator, empty,
                    current.start, after_operator, operator_pos,
                )

            pos = after_operator
            break

        right, new_pos = _parse_primary(s, after_operator, end)

        if right is None or new_pos <= after_operator:
            break

        if operator == "/":
            current = FracNode(
                current, right, operator_pos,
                current.start, new_pos,
            )
        else:
            current = BinaryNode(
                current, operator, right,
                current.start, new_pos, operator_pos,
            )

        pos = new_pos

    return current, pos


def _parse_primary(
    s: str,
    pos: int,
    end: int,
) -> Tuple[Term | None, int]:

    pos = _skip_spaces(s, pos, end)

    if pos >= end:
        return TextNode("", pos, pos), pos

    start = pos

    if s[pos] == "{":
        return _parse_structural_group(s, pos, end)

    if s[pos] == "(":
        inner, close_pos = _parse_parenthesis_group(s, pos, end)
        return (
            GroupNode(
                inner=inner,
                start=start,
                end=close_pos,
                left_pos=start,
                right_pos=max(start, close_pos - 1),
                visible=True,
            ),
            close_pos,
        )

    if s[pos] in ")}":
        return None, pos

    match = ATOM_CHARS_RE.match(s, pos)

    if match is not None:
        atom_end = match.end()
        return AtomNode(s[pos:atom_end], pos, atom_end), atom_end

    return TextNode(s[pos], pos, pos + 1), pos + 1


# ============================================================================
# Structural groups / fractions
# ============================================================================

def _parse_structural_group(
    s: str,
    pos: int,
    end: int,
) -> Tuple[Term, int]:

    open_pos = pos
    depth = 1
    cursor = pos + 1

    while cursor < end and depth > 0:
        if s[cursor] == "{":
            depth += 1
        elif s[cursor] == "}":
            depth -= 1
        cursor += 1

    if depth == 0:
        inner_end = cursor - 1
        close_pos = cursor - 1
        next_pos = cursor
    else:
        inner_end = end
        close_pos = end
        next_pos = end

    slash_pos = _find_top_level_slash(s, open_pos + 1, inner_end)

    if slash_pos is not None:
        numerator_start = open_pos + 1
        numerator_end = slash_pos
        denominator_start = slash_pos + 1
        denominator_end = inner_end

        numerator_sequence, _ = _parse_additive_expression(
            s, numerator_start, numerator_end
        )
        denominator_sequence, _ = _parse_additive_expression(
            s, denominator_start, denominator_end
        )

        numerator = _sequence_as_term(
            numerator_sequence, numerator_start, numerator_end
        )
        denominator = _sequence_as_term(
            denominator_sequence, denominator_start, denominator_end
        )

        return FracNode(
            numerator=numerator,
            denominator=denominator,
            slash_pos=slash_pos,
            start=open_pos,
            end=next_pos,
            open_pos=open_pos,
            close_pos=close_pos,
        ), next_pos

    inner, _ = _parse_additive_expression(s, open_pos + 1, inner_end)

    return GroupNode(
        inner=inner,
        start=open_pos,
        end=next_pos,
        left_pos=open_pos,
        right_pos=max(open_pos, close_pos),
        visible=False,
    ), next_pos


def _sequence_as_term(
    sequence: Sequence,
    start: int,
    end: int,
) -> Term:

    if not sequence:
        return TextNode("", start, start)

    if len(sequence) == 1:
        _, term = sequence[0]
        return term

    return GroupNode(
        inner=sequence,
        start=start,
        end=end,
        left_pos=start,
        right_pos=max(start, end - 1),
        visible=False,
    )


def _find_top_level_slash(s: str, start: int, end: int):
    brace_depth = 0
    paren_depth = 0

    for index in range(start, end):
        ch = s[index]

        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
        elif ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
        elif ch == "/" and brace_depth == 0 and paren_depth == 0:
            return index

    return None


def _parse_brace_group(s: str, pos: int, end: int):
    term, close_pos = _parse_structural_group(s, pos, end)

    if isinstance(term, FracNode):
        return [("", term)], close_pos

    if isinstance(term, GroupNode):
        return term.inner, close_pos

    return [("", term)], close_pos


def _parse_parenthesis_group(
    s: str,
    pos: int,
    end: int,
) -> Tuple[Sequence, int]:

    depth = 1
    cursor = pos + 1

    while cursor < end and depth > 0:
        if s[cursor] == "(":
            depth += 1
        elif s[cursor] == ")":
            depth -= 1
        cursor += 1

    if depth == 0:
        inner_end = cursor - 1
        close_pos = cursor
    else:
        inner_end = end
        close_pos = end

    inner, _ = _parse_additive_expression(s, pos + 1, inner_end)
    return inner, close_pos


# ============================================================================
# Layout
# ============================================================================

def format_op(op: str) -> str:
    return f" {op} "


def _pad_lines(lines: List[str], left: int, right: int) -> List[str]:
    return [" " * left + line + " " * right for line in lines]


def _render_parentheses(lines: List[str]) -> List[str]:
    if not lines:
        return ["()"]

    if len(lines) == 1:
        return ["(" + lines[0] + ")"]

    result = []

    for index, line in enumerate(lines):
        if index == 0:
            left, right = "⎛", "⎞"
        elif index == len(lines) - 1:
            left, right = "⎝", "⎠"
        else:
            left, right = "⎜", "⎟"

        result.append(left + line + right)

    return result


def layout_term(term: Term) -> Tuple[List[str], int, int]:

    if isinstance(term, (AtomNode, TextNode)):
        return [term.text], 0, len(term.text)

    if isinstance(term, GroupNode):
        lines, baseline, width = layout_sequence(term.inner)

        if not term.visible:
            return lines, baseline, width

        rendered = _render_parentheses(lines)
        return rendered, baseline, max(len(line) for line in rendered)

    if isinstance(term, BinaryNode):
        left_lines, left_base, left_width = layout_term(term.left)
        right_lines, right_base, right_width = layout_term(term.right)

        top = max(left_base, right_base)

        bottom = max(
            len(left_lines) - left_base - 1,
            len(right_lines) - right_base - 1,
        )

        height = top + 1 + bottom

        left_full = (
            [" " * left_width] * (top - left_base)
            + left_lines
            + [" " * left_width] * (
                height - (top - left_base) - len(left_lines)
            )
        )

        right_full = (
            [" " * right_width] * (top - right_base)
            + right_lines
            + [" " * right_width] * (
                height - (top - right_base) - len(right_lines)
            )
        )

        op = format_op(term.operator)
        output = []

        for row in range(height):
            # FIX: show the operator only on the shared baseline.
            # Reserve its width on other rows to keep operands aligned.
            operator = op if row == top else " " * len(op)

            output.append(
                left_full[row]
                + operator
                + right_full[row]
            )

        return output, top, left_width + len(op) + right_width

    if isinstance(term, FracNode):
        num_lines, _, num_width = layout_term(term.numerator)
        den_lines, _, den_width = layout_term(term.denominator)

        content_width = max(num_width, den_width, 1)
        bar_width = content_width + 2

        num_left = (bar_width - num_width) // 2
        num_right = bar_width - num_width - num_left

        den_left = (bar_width - den_width) // 2
        den_right = bar_width - den_width - den_left

        numerator = _pad_lines(num_lines, num_left, num_right)
        denominator = _pad_lines(den_lines, den_left, den_right)

        lines = numerator + ["-" * bar_width] + denominator
        return lines, len(numerator), bar_width

    raise TypeError(f"Unknown term type: {term!r}")


def layout_sequence(seq: Sequence) -> Tuple[List[str], int, int]:
    if not seq:
        return [""], 0, 0

    blocks = []

    for op, term in seq:
        lines, baseline, width = layout_term(term)
        blocks.append((op, lines, baseline, width))

    top = max(baseline for _, _, baseline, _ in blocks)
    bottom = max(
        len(lines) - baseline - 1
        for _, lines, baseline, _ in blocks
    )

    height = top + 1 + bottom
    output = [""] * height

    for index, (op, lines, baseline, width) in enumerate(blocks):
        above = top - baseline
        below = height - above - len(lines)

        padded = [" " * width] * above + lines + [" " * width] * below

        operator = format_op(op) if index != 0 and op else ""

        for row in range(height):
            prefix = operator if row == top else " " * len(operator)
            output[row] += prefix + padded[row]

    width = max((len(line) for line in output), default=0)
    return output, top, width


def render_line(line: str) -> List[str]:
    if not line.strip():
        return []

    sequence = parse_line(line)
    lines, _, _ = layout_sequence(sequence)
    return lines


# ============================================================================
# Cursor mapping
# ============================================================================

def locate_cursor(line: str, raw_col: int) -> Tuple[int, int]:
    raw_col = max(0, min(raw_col, len(line)))
    sequence = parse_line(line)

    if not sequence:
        return 0, 0

    return _locate_sequence(sequence, raw_col)


def _locate_sequence(sequence: Sequence, raw_col: int) -> Tuple[int, int]:
    if not sequence:
        return 0, 0

    blocks = []

    for op, term in sequence:
        lines, baseline, width = layout_term(term)
        blocks.append((op, term, lines, baseline, width))

    top = max(baseline for _, _, _, baseline, _ in blocks)
    accumulated = 0

    for index, (op, term, lines, baseline, width) in enumerate(blocks):
        operator = format_op(op) if index != 0 and op else ""
        block_start = accumulated + len(operator)

        if raw_col <= term.start:
            return top - baseline, block_start

        if raw_col <= term.end:
            row, col = _locate_term(term, raw_col)

            return (
                row + top - baseline,
                block_start + col,
            )

        accumulated += len(operator) + width

    return top, accumulated


def _locate_term(term: Term, raw_col: int) -> Tuple[int, int]:
    if isinstance(term, (AtomNode, TextNode)):
        return 0, max(0, min(raw_col - term.start, len(term.text)))

    if isinstance(term, GroupNode):
        if raw_col <= term.start:
            return 0, 0

        if raw_col >= term.end:
            lines, baseline, width = layout_sequence(term.inner)
            return baseline, width

        return _locate_sequence(term.inner, raw_col)

    if isinstance(term, BinaryNode):
        if raw_col <= term.left.end:
            return _locate_term(term.left, raw_col)

        right_row, right_col = _locate_term(term.right, raw_col)
        _, left_base, left_width = layout_term(term.left)
        _, right_base, _ = layout_term(term.right)

        top = max(left_base, right_base)

        return (
            right_row + top - right_base,
            left_width + len(format_op(term.operator)) + right_col,
        )

    if isinstance(term, FracNode):
        return _locate_frac(term, raw_col)

    raise TypeError(f"Unknown term type: {term!r}")


def _locate_frac(term: FracNode, raw_col: int) -> Tuple[int, int]:
    num_lines, num_base, num_width = layout_term(term.numerator)
    den_lines, den_base, den_width = layout_term(term.denominator)

    content_width = max(num_width, den_width, 1)
    bar_width = content_width + 2

    num_left = (bar_width - num_width) // 2
    den_left = (bar_width - den_width) // 2

    if term.open_pos >= 0:
        if raw_col <= term.open_pos:
            return num_base, 0

        if raw_col <= term.slash_pos:
            row, col = _locate_term(term.numerator, raw_col)
            return row, num_left + col

        if raw_col <= term.close_pos:
            if raw_col == term.slash_pos + 1:
                return len(num_lines) + 1, den_left

            row, col = _locate_term(term.denominator, raw_col)

            return (
                len(num_lines) + 1 + row,
                den_left + col,
            )

        return num_base, bar_width

    if raw_col <= term.start:
        return num_base, 0

    if raw_col <= term.slash_pos:
        row, col = _locate_term(term.numerator, raw_col)
        return row, num_left + col

    if raw_col <= term.end:
        if raw_col == term.slash_pos + 1:
            return len(num_lines) + 1, den_left

        row, col = _locate_term(term.denominator, raw_col)

        return (
            len(num_lines) + 1 + row,
            den_left + col,
        )

    return num_base, bar_width


# ============================================================================
# Cursor stops
# ============================================================================

def cursor_stops(line: str) -> List[int]:
    return list(range(len(line) + 1))


def next_stop(line: str, col: int) -> int:
    col = max(0, min(col, len(line)))

    if col >= len(line):
        return len(line)

    return col + 1


def prev_stop(line: str, col: int) -> int:
    col = max(0, min(col, len(line)))

    if col <= 0:
        return 0

    return col - 1


# ============================================================================
# Fraction insertion
# ============================================================================

def _find_matching_open(
    line: str,
    close_pos: int,
    open_char: str,
    close_char: str,
):
    depth = 0

    for index in range(close_pos, -1, -1):
        if line[index] == close_char:
            depth += 1
        elif line[index] == open_char:
            depth -= 1

            if depth == 0:
                return index

    return None


def _find_previous_operand(line: str, col: int):
    pos = col

    while pos > 0 and line[pos - 1].isspace():
        pos -= 1

    if pos <= 0:
        return None

    end = pos

    if line[pos - 1].isalnum() or line[pos - 1] in "_.":
        pos -= 1

        while (
            pos > 0
            and (line[pos - 1].isalnum() or line[pos - 1] in "_.")
        ):
            pos -= 1

        return pos, end

    if line[pos - 1] in ")}":
        close_char = line[pos - 1]
        open_char = "(" if close_char == ")" else "{"

        open_pos = _find_matching_open(
            line, pos - 1, open_char, close_char
        )

        if open_pos is not None:
            return open_pos, end

    return None


def insert_fraction(line: str, col: int):
    operand = _find_previous_operand(line, col)

    if operand is None:
        return line[:col] + "/" + line[col:], col + 1

    start, end = operand
    selected = line[start:end]
    replacement = "{" + selected + "/}"

    new_line = line[:start] + replacement + line[end:]
    new_col = start + 1 + len(selected) + 1

    return new_line, new_col


def make_fraction_from_selection(line: str, start: int, end: int):
    selected = line[start:end]
    replacement = "{" + selected + "/}"

    new_line = line[:start] + replacement + line[end:]
    new_col = start + 1 + len(selected) + 1

    return new_line, new_col


# ============================================================================
# Fraction discovery
# ============================================================================

def find_fraction_at_cursor(line: str, col: int):
    sequence = parse_line(line)
    return _find_fraction_containing_cursor(sequence, col)


def _find_fraction_containing_cursor(sequence: Sequence, col: int):
    for _, term in sequence:
        found = _find_fraction_in_term(term, col)

        if found is not None:
            return found

    return None


def _find_fraction_in_term(term: Term, col: int):
    if isinstance(term, FracNode):
        found = _find_fraction_in_term(term.numerator, col)

        if found is not None:
            return found

        found = _find_fraction_in_term(term.denominator, col)

        if found is not None:
            return found

        if term.start <= col <= term.end:
            return term

        return None

    if isinstance(term, GroupNode):
        return _find_fraction_containing_cursor(term.inner, col)

    if isinstance(term, BinaryNode):
        found = _find_fraction_in_term(term.left, col)

        if found is not None:
            return found

        return _find_fraction_in_term(term.right, col)

    return None


# ============================================================================
# Fraction collapse
# ============================================================================

def collapse_fraction(line: str, col: int):
    """
    Delete the slash boundary when DELETE is pressed immediately after
    the slash.

    Example:
        {a/|b} -> ab
    """

    frac = find_fraction_at_cursor(line, col)

    if frac is None or col != frac.slash_pos + 1:
        return None

    if frac.open_pos >= 0:
        numerator = line[frac.open_pos + 1:frac.slash_pos]
        denominator = line[frac.slash_pos + 1:frac.close_pos]
        replacement = numerator + denominator

        new_line = line[:frac.start] + replacement + line[frac.end:]
        new_col = frac.start + len(numerator)

        return new_line, new_col

    numerator = line[frac.start:frac.slash_pos]
    denominator = line[frac.slash_pos + 1:frac.end]
    replacement = numerator + denominator

    new_line = line[:frac.start] + replacement + line[frac.end:]
    new_col = frac.start + len(numerator)

    return new_line, new_col


# ============================================================================
# Compatibility helpers
# ============================================================================

def fraction_ends_at_cursor(line: str, col: int):
    if col < 0 or col >= len(line) or line[col] != "}":
        return False

    frac = find_fraction_at_cursor(line, col)

    if frac is None:
        return False

    return frac.close_pos == col


def move_out_of_fraction(line: str, col: int):
    if fraction_ends_at_cursor(line, col):
        return col + 1

    return col


def widen_numerator_for_edit(line: str, col: int):
    sequence = parse_line(line)
    frac = _find_fraction_containing_cursor(sequence, col)

    if frac is None:
        return None

    if frac.numerator.start < col <= frac.numerator.end:
        return line, col

    return None


def try_close_fraction(line: str, col: int):
    return None
