"""
The parsing + layout engine for plainmath's math blocks.

Grammar (recursive, so fractions can nest):
    Sequence := Term ( ('+'|'-') Term )*
    Term     := Frac | Group | Atom
    Group    := '(' Sequence ')'                      (always balanced —
                only ever created by the app itself, see plainmath.py)
    Frac     := (Group | Atom) '/' (Group | Sequence-to-end-of-input)
    Atom     := run of [A-Za-z0-9_.]

Denominators default to "everything to the end of input" (greedy) unless
explicitly closed with parens — which the app inserts automatically when
you press Right at the true end of an open denominator. That single rule
is what makes "a/b" + Right + "+3" turn into "a/(b)+3", rendered as the
fraction a-over-b with "+ 3" trailing at the baseline.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Union

ATOM_CHARS_RE = re.compile(r"[A-Za-z0-9_.]")
STOP_TOKEN_RE = re.compile(r"[A-Za-z0-9_.]+|[+\-/=*]")


@dataclass
class AtomNode:
    text: str
    start: int
    end: int


@dataclass
class TextNode:
    """A run of ordinary prose — spaces, words, punctuation — that sits
    at the baseline like a plain atom, but is never itself a candidate
    numerator/denominator (only a real Atom or Group can be that)."""
    text: str
    start: int
    end: int


@dataclass
class GroupNode:
    inner: "Sequence"
    start: int  # position of '('
    end: int    # position right after the matching ')'


@dataclass
class FracNode:
    numerator: "Term"
    denominator: "Sequence"
    slash_pos: int
    den_start: int
    den_end: int
    den_explicit: bool
    start: int
    end: int


Term = Union[AtomNode, TextNode, GroupNode, FracNode]
Sequence = List[Tuple[str, Term]]


# ---------------------------------------------------------------- parsing

def parse_line(line: str) -> Sequence:
    if not line:
        return []
    seq, _ = _parse_sequence(line, 0, len(line))
    return seq


OPERATOR_CHARS = "+-=*"


def _is_prose_char(ch: str) -> bool:
    """True for characters that are just ordinary prose — spaces, words'
    punctuation, etc — as opposed to math syntax we actively parse."""
    return not (ch.isalnum() or ch in "_.(/)" + OPERATOR_CHARS)


def _parse_sequence(s: str, pos: int, end: int) -> Tuple[Sequence, int]:
    terms: Sequence = []
    first = True
    while pos < end:
        op = ""
        if not first and s[pos] in OPERATOR_CHARS:
            op = s[pos]
            pos += 1
        if pos >= end:
            if op:
                # A trailing operator with nothing after it (e.g. the user
                # just typed "a+") still needs a term so it isn't silently
                # dropped from the parse — otherwise it never renders and
                # cursor math for this line falls out of sync with the
                # raw text. Give it an empty placeholder term.
                terms.append((op, TextNode(text="", start=pos, end=pos)))
            break
        if _is_prose_char(s[pos]):
            j = pos
            while j < end and _is_prose_char(s[j]):
                j += 1
            node: Term = TextNode(text=s[pos:j], start=pos, end=j)
            pos = j
        else:
            node, pos = _parse_term(s, pos, end)
        terms.append((op, node))
        first = False
    return terms, pos


def _parse_term(s: str, pos: int, end: int) -> Tuple[Term, int]:
    start = pos
    if pos < end and s[pos] == "(":
        inner_seq, close_pos = _parse_group(s, pos, end)
        node: Term = GroupNode(inner=inner_seq, start=start, end=close_pos)
        pos = close_pos
    else:
        j = pos
        while j < end and ATOM_CHARS_RE.match(s[j]):
            j += 1
        node = AtomNode(text=s[pos:j], start=pos, end=j)
        pos = j

    if pos < end and s[pos] == "/":
        slash_pos = pos
        pos += 1
        if pos < end and s[pos] == "(":
            den_seq, close_pos = _parse_group(s, pos, end)
            frac = FracNode(
                numerator=node, denominator=den_seq, slash_pos=slash_pos,
                den_start=pos + 1, den_end=close_pos - 1, den_explicit=True,
                start=start, end=close_pos,
            )
            pos = close_pos
        else:
            den_seq, new_pos = _parse_sequence(s, pos, end)
            frac = FracNode(
                numerator=node, denominator=den_seq, slash_pos=slash_pos,
                den_start=pos, den_end=new_pos, den_explicit=False,
                start=start, end=new_pos,
            )
            pos = new_pos
        return frac, pos

    return node, pos


def _parse_group(s: str, pos: int, end: int) -> Tuple[Sequence, int]:
    depth = 1
    j = pos + 1
    while j < end and depth > 0:
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
        j += 1
    close_pos = j
    inner_seq, _ = _parse_sequence(s, pos + 1, close_pos - 1)
    return inner_seq, close_pos


def _term_span(term: Term) -> Tuple[int, int]:
    return term.start, term.end


# ---------------------------------------------------------------- layout

def format_op(op: str) -> str:
    return f" {op} "


def layout_term(term: Term) -> Tuple[List[str], int, int]:
    """Returns (lines, baseline_row, width)."""
    if isinstance(term, (AtomNode, TextNode)):
        text = term.text
        return [text], 0, len(text)

    if isinstance(term, GroupNode):
        return layout_sequence(term.inner)

    if isinstance(term, FracNode):
        num_lines, _num_baseline, num_width = layout_term(term.numerator)
        den_lines, _den_baseline, den_width = layout_sequence(term.denominator)
        content_width = max(num_width, den_width, 1)
        bar_width = content_width + 2

        num_pad_l = (bar_width - num_width) // 2
        num_pad_r = bar_width - num_width - num_pad_l
        den_pad_l = (bar_width - den_width) // 2
        den_pad_r = bar_width - den_width - den_pad_l

        padded_num = [(" " * num_pad_l) + l + (" " * num_pad_r) for l in num_lines]
        padded_den = [(" " * den_pad_l) + l + (" " * den_pad_r) for l in den_lines]

        lines = padded_num + ["-" * bar_width] + padded_den
        baseline = len(padded_num)
        return lines, baseline, bar_width

    raise TypeError(f"unknown term type: {term!r}")


def layout_sequence(seq: Sequence) -> Tuple[List[str], int, int]:
    if not seq:
        return [""], 0, 0

    blocks = []
    for op, term in seq:
        lines, baseline, width = layout_term(term)
        blocks.append((op, lines, baseline, width))

    top = max(b for (_, _, b, _) in blocks)
    bottom = max(len(l) - b - 1 for (_, l, b, _) in blocks)
    height = top + 1 + bottom

    out_lines = [""] * height
    for idx, (op, lines, baseline, width) in enumerate(blocks):
        pad_above = top - baseline
        pad_below = height - pad_above - len(lines)
        full = ([" " * width] * pad_above) + lines + ([" " * width] * pad_below)
        op_str = format_op(op) if (idx != 0 and op) else ""
        for r in range(height):
            filler = op_str if r == top else " " * len(op_str)
            out_lines[r] += filler + full[r]

    total_width = len(out_lines[0]) if out_lines else 0
    return out_lines, top, total_width


def render_line(line: str) -> List[str]:
    if not line.strip():
        return []
    seq = parse_line(line)
    lines, _baseline, _width = layout_sequence(seq)
    return lines


# ---------------------------------------------------------- cursor mapping

def locate_cursor(line: str, raw_col: int) -> Tuple[int, int]:
    seq = parse_line(line)
    if not seq:
        return 0, 0
    return _locate_in_sequence(seq, raw_col)


def _locate_in_sequence(seq: Sequence, raw_offset: int) -> Tuple[int, int]:
    if not seq:
        return 0, 0

    blocks = []
    for op, term in seq:
        lines, baseline, width = layout_term(term)
        blocks.append((op, term, lines, baseline, width))

    top = max(b for (_, _, _, b, _) in blocks)
    col_acc = 0
    for idx, (op, term, lines, baseline, width) in enumerate(blocks):
        op_str = format_op(op) if (idx != 0 and op) else ""
        _t_start, t_end = _term_span(term)
        if raw_offset <= t_end:
            pad_above = top - baseline
            r, c = _locate_in_term(term, raw_offset)
            return r + pad_above, col_acc + len(op_str) + c
        col_acc += len(op_str) + width

    # Past every term: rest at the end, on the baseline row.
    return top, col_acc


def _locate_in_term(term: Term, raw_offset: int) -> Tuple[int, int]:
    if isinstance(term, (AtomNode, TextNode)):
        c = max(0, min(raw_offset - term.start, len(term.text)))
        return 0, c

    if isinstance(term, GroupNode):
        inner_start, inner_end = term.start + 1, term.end - 1
        clamped = max(inner_start, min(raw_offset, inner_end))
        return _locate_in_sequence(term.inner, clamped)

    if isinstance(term, FracNode):
        num_lines, _nb, num_width = layout_term(term.numerator)
        den_lines, _db, den_width = layout_sequence(term.denominator)
        content_width = max(num_width, den_width, 1)
        bar_width = content_width + 2
        num_pad_l = (bar_width - num_width) // 2
        den_pad_l = (bar_width - den_width) // 2

        if raw_offset <= term.slash_pos:
            _num_start, num_end = _term_span(term.numerator)
            r, c = _locate_in_term(term.numerator, min(raw_offset, num_end))
            return r, num_pad_l + c

        clamped = max(term.den_start, min(raw_offset, term.den_end))
        r, c = _locate_in_sequence(term.denominator, clamped)
        row_base = len(num_lines) + 1
        return row_base + r, den_pad_l + c

    raise TypeError(f"unknown term type: {term!r}")


# --------------------------------------------------------- element stops

def cursor_stops(line: str) -> List[int]:
    stops = {0, len(line)}
    for m in STOP_TOKEN_RE.finditer(line):
        if m.group(0)[0] in OPERATOR_CHARS:
            # Operators (+ - = *) are single-character elements: you can
            # stand right before or right after one, but never "inside"
            # it — there's nothing to step into.
            stops.add(m.start())
            stops.add(m.end())
        else:
            # A run of atom characters (a variable name like "Re", or
            # several single-char variables sitting next to each other
            # like "ab") is still made of ordinary characters underneath.
            # Expose every position inside it, not just its two ends, so
            # Left/Right can land in the middle ("R|e") just like it
            # would in a plain text file.
            for p in range(m.start(), m.end() + 1):
                stops.add(p)
    return sorted(stops)


def next_stop(line: str, col: int) -> int:
    for s in cursor_stops(line):
        if s > col:
            return s
    return len(line)


def prev_stop(line: str, col: int) -> int:
    prev = 0
    for s in cursor_stops(line):
        if s >= col:
            break
        prev = s
    return prev


# ------------------------------------------------------- exit-and-wrap

def _find_innermost_open_frac(seq: Sequence):
    if not seq:
        return None
    _op, term = seq[-1]
    if isinstance(term, FracNode) and not term.den_explicit:
        inner = _find_innermost_open_frac(term.denominator)
        return inner if inner is not None else term
    return None


def _find_frac_numerator_edit(seq: Sequence, col: int):
    """Recursively search a parsed sequence for a FracNode whose bare
    (un-grouped) Atom numerator spans raw column `col` — i.e. the
    cursor sits anywhere at or inside that numerator, immediately
    before the fraction's slash. This covers the cursor sitting at the
    very start of the numerator ("|b/b"), in the middle of a
    multi-character one ("R|e/im"), or right at its end ("b|/b") —
    editing at any of those spots should widen the numerator, not just
    the boundary right before the slash.

    A numerator that's already an explicit Group only needs help when
    the cursor sits exactly at its right edge, right before the slash;
    edits *inside* an existing group are already safe on their own,
    since the group protects its contents from the slash reinterpreting
    them."""
    for _op, term in seq:
        if isinstance(term, FracNode):
            num = term.numerator
            if isinstance(num, GroupNode):
                if term.slash_pos == col:
                    return term
                found = _find_frac_numerator_edit(num.inner, col)
                if found is not None:
                    return found
            else:
                if num.start <= col <= num.end:
                    return term
            found = _find_frac_numerator_edit(term.denominator, col)
            if found is not None:
                return found
        elif isinstance(term, GroupNode):
            found = _find_frac_numerator_edit(term.inner, col)
            if found is not None:
                return found
    return None


def widen_numerator_for_edit(line: str, col: int):
    """If the cursor sits at, or anywhere inside, a fraction's bare
    (un-grouped) numerator, typing something that isn't a plain atom
    character there — "+", "-", a space, "(", etc. — would otherwise
    get spliced into the raw text right where it stands, which the
    parser then reinterprets around the slash rather than treating it
    as part of the numerator you're sitting in (e.g. "b/b" + cursor
    before the first "b" + typing "a+" naively becomes "a+b/b", which
    parses as "a + (b/b)", not "(a+b)/b").

    This wraps the whole numerator in an explicit group first (the same
    mechanism the '/' key already uses for a highlighted numerator —
    it renders with no visible parens, just a proper stacked fraction)
    and returns the edit point shifted to land in the same logical spot
    inside it. If the numerator is already an explicit group and the
    cursor is right at its boundary before the slash, no rewrite is
    needed — just step the cursor inside it.

    Returns (new_line, new_col), or None if the cursor isn't at such a
    spot and no special handling is needed.
    """
    seq = parse_line(line)
    frac = _find_frac_numerator_edit(seq, col)
    if frac is None:
        return None

    if isinstance(frac.numerator, GroupNode):
        return line, frac.numerator.end - 1

    start, end = frac.numerator.start, frac.numerator.end
    new_line = line[:start] + "(" + line[start:end] + ")" + line[end:]
    new_col = col + 1
    return new_line, new_col


def try_close_fraction(line: str, col: int):
    """If the cursor is at the true end of the line and there's an open
    (un-parenthesized) fraction denominator there, wrap it in parens.
    Returns (new_line, new_col) or None if nothing to close."""
    if col != len(line):
        return None
    seq = parse_line(line)
    frac = _find_innermost_open_frac(seq)
    if frac is None:
        return None
    new_line = line[:frac.den_start] + "(" + line[frac.den_start:] + ")"
    return new_line, len(new_line)