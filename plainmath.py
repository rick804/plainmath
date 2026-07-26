#!/usr/bin/env python3
"""
plainmath — a terminal-native structured math editor that renders
editable 2D equations using plain text.

Proof of concept:
  - Opens a plain-text file.
  - Recognizes $$ ... $$ blocks ("Math Mode" regions).
  - Detects simple a/b expressions inside those blocks and renders
    them live as stacked fractions in a preview pane.
  - Treats a math block as one structural unit: Up/Down while the
    cursor sits inside a block jumps over the whole block instead of
    line by line.
  - Ctrl+S saves the file. The file on disk always stores the plain
    "a/b" form — only the preview is rendered as 2D math.

Usage:
    python plainmath.py <file>
"""

import re
import sys
from dataclasses import dataclass

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style

MATH_OPEN = "$$"
MATH_CLOSE = "$$"

# Matches a simple "a/b" fraction expression, e.g. "a+b/c+d" or "3/4"
FRACTION_RE = re.compile(r"^(.*)/(.*)$")


@dataclass
class MathBlock:
    start_line: int  # line index of the opening $$
    end_line: int    # line index of the closing $$


def find_math_blocks(lines: list[str]) -> list[MathBlock]:
    """Scan the file's lines and return the (start, end) of each $$ block."""
    blocks = []
    open_line = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == MATH_OPEN and open_line is None:
            open_line = i
        elif stripped == MATH_CLOSE and open_line is not None:
            blocks.append(MathBlock(open_line, i))
            open_line = None
    return blocks


def render_fraction(expr: str) -> list[str]:
    """Turn 'a/b' into a stacked ASCII fraction. Falls back to the raw
    expression if it doesn't look like a simple fraction."""
    expr = expr.strip()
    match = FRACTION_RE.match(expr)
    if not match:
        return [expr] if expr else []

    numerator, denominator = match.group(1).strip(), match.group(2).strip()
    width = max(len(numerator), len(denominator), 1)
    return [
        numerator.center(width),
        "-" * width,
        denominator.center(width),
    ]


def render_math_block(lines: list[str], block: MathBlock) -> list[str]:
    """Render the full contents of one math block as 2D math lines."""
    inner = lines[block.start_line + 1:block.end_line]
    rendered: list[str] = []
    for raw in inner:
        rendered.extend(render_fraction(raw))
    return rendered if rendered else ["(empty math block)"]


def block_at_line(blocks: list[MathBlock], line_no: int) -> MathBlock | None:
    for b in blocks:
        if b.start_line <= line_no <= b.end_line:
            return b
    return None


def build_preview_text(lines: list[str], cursor_line: int) -> str:
    blocks = find_math_blocks(lines)
    current = block_at_line(blocks, cursor_line)
    if current is None:
        return "(place cursor inside a $$ ... $$ block to preview it)"
    rendered = render_math_block(lines, current)
    return "\n".join(rendered)


def cursor_line_of(buffer: Buffer) -> int:
    return buffer.document.cursor_position_row


def make_app(filepath: str) -> Application:
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    buffer = Buffer(document=Document(text, 0), multiline=True)

    def get_preview_text():
        lines = buffer.text.split("\n")
        return build_preview_text(lines, cursor_line_of(buffer))

    editor_window = Window(content=BufferControl(buffer=buffer), wrap_lines=False)
    preview_window = Window(
        content=FormattedTextControl(get_preview_text),
        height=6,
        style="class:preview",
    )
    status_window = Window(
        content=FormattedTextControl(
            lambda: f" {filepath}  —  Ctrl+S save   Ctrl+C quit"
        ),
        height=1,
        style="class:status",
    )

    root_container = HSplit(
        [
            editor_window,
            Window(height=1, char="-", style="class:divider"),
            preview_window,
            status_window,
        ]
    )

    bindings = KeyBindings()

    @bindings.add("c-s")
    def _save(event):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(buffer.text)

    @bindings.add("c-c")
    def _quit(event):
        event.app.exit()

    @bindings.add("up")
    def _up(event):
        lines = buffer.text.split("\n")
        blocks = find_math_blocks(lines)
        row = cursor_line_of(buffer)
        current = block_at_line(blocks, row)
        if current is not None and row != current.start_line:
            # Jump the whole block as one structural unit.
            target_row = current.start_line
            buffer.cursor_position = buffer.document.translate_row_col_to_index(
                target_row, 0
            )
        else:
            buffer.cursor_up()

    @bindings.add("down")
    def _down(event):
        lines = buffer.text.split("\n")
        blocks = find_math_blocks(lines)
        row = cursor_line_of(buffer)
        current = block_at_line(blocks, row)
        if current is not None and row != current.end_line:
            target_row = current.end_line
            buffer.cursor_position = buffer.document.translate_row_col_to_index(
                target_row, 0
            )
        else:
            buffer.cursor_down()

    style = Style.from_dict(
        {
            "preview": "bg:#1c1c1c #00ff5f",
            "status": "bg:#444444 #ffffff",
            "divider": "#666666",
        }
    )

    return Application(
        layout=Layout(root_container, focused_element=editor_window),
        key_bindings=bindings,
        style=style,
        full_screen=True,
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python plainmath.py <file>")
        sys.exit(1)

    app = make_app(sys.argv[1])
    app.run()


if __name__ == "__main__":
    main()
