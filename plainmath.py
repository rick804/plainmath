#!/usr/bin/env python3
"""
plainmath — a terminal-native structured math editor that renders
editable 2D equations using plain text.

Proof of concept:
  - Opens a plain-text file.
  - If a line reading exactly "PLAINMATH" appears anywhere in the file,
    every line AFTER it is treated as math and rendered live — no
    per-block delimiters needed. Everything above (and the flag line
    itself) stays as plain, unrendered text.
  - As you type, "a/b" is rendered immediately, in place, as a stacked
    fraction — no separate preview pane.
  - Numerator defaults to the single token right before "/". Highlight
    a wider expression and press "/" to make the highlight the
    numerator instead (it gets wrapped in parens under the hood).
  - Denominator is everything after "/" to the end of the line.
  - In math mode, Left/Right move element-by-element (whole tokens,
    not characters). Above the flag (plain text), they move char by
    char as usual. Up/Down always move one real line at a time.
  - Ctrl+S saves. The file on disk always stores the plain "a/b" form
    — only the display is rendered as 2D math.

Usage:
    python plainmath.py <file>
"""

import sys

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.styles import Style

from engine import render_line, locate_cursor, next_stop, prev_stop

PLAINMATH_FLAG = "PLAINMATH"


def find_math_start(lines: list[str]) -> int | None:
    """Return the index of the first line that is IN math mode (i.e. the
    line right after the PLAINMATH flag), or None if the flag isn't
    present anywhere in the file."""
    for i, line in enumerate(lines):
        if line.strip().upper() == PLAINMATH_FLAG:
            return i + 1
    return None


class MathEditorControl(UIControl):
    """Renders the buffer's text with math-mode lines transformed in
    place, while keystrokes still edit the plain-text buffer underneath."""

    def __init__(self, buffer: Buffer):
        self.buffer = buffer

    def is_focusable(self) -> bool:
        return True

    def create_content(self, width: int, height: int) -> UIContent:
        text = self.buffer.text
        lines = text.split("\n")
        cursor_row, cursor_col = self.buffer.document.translate_index_to_position(
            self.buffer.cursor_position
        )
        math_start = find_math_start(lines)

        output: list[list[tuple[str, str]]] = []
        cursor_point = None

        for i, line in enumerate(lines):
            in_math = math_start is not None and i >= math_start

            if in_math:
                try:
                    rendered = render_line(line)
                    if not rendered:
                        rendered = [""]
                    cur_row, cur_col = (0, cursor_col)
                    if i == cursor_row:
                        cur_row, cur_col = locate_cursor(line, cursor_col)
                except Exception:
                    # Never let a math-rendering edge case silently freeze
                    # the screen (and hide where the cursor really is) —
                    # fall back to showing this line as plain text instead.
                    rendered = [line]
                    cur_row, cur_col = 0, cursor_col
                for r_idx, r_line in enumerate(rendered):
                    output.append([("class:math", r_line)])
                    if i == cursor_row and r_idx == cur_row:
                        cursor_point = Point(x=cur_col, y=len(output) - 1)
            else:
                output.append([("", line)])
                if i == cursor_row:
                    cursor_point = Point(x=cursor_col, y=len(output) - 1)

        if cursor_point is None:
            cursor_point = Point(x=0, y=0)
        if not output:
            output = [[("", "")]]

        def get_line(i: int):
            return output[i]

        return UIContent(
            get_line=get_line,
            line_count=len(output),
            cursor_position=cursor_point,
            show_cursor=True,
        )


def cursor_line_of(buffer: Buffer) -> int:
    return buffer.document.cursor_position_row


def make_app(filepath: str) -> Application:
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    buffer = Buffer(document=Document(text, 0), multiline=True)

    editor_window = Window(content=MathEditorControl(buffer), wrap_lines=False)
    status_window = Window(
        content=FormattedTextControl(
            lambda: f" {filepath}  —  Ctrl+S save   Ctrl+C quit   "
            f"Shift+Arrow to highlight, then '/' for a custom numerator"
        ),
        height=1,
        style="class:status",
    )

    root_container = HSplit([editor_window, status_window])

    bindings = KeyBindings()

    @bindings.add("c-s")
    def _save(event):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(buffer.text)

    @bindings.add("c-c")
    def _quit(event):
        event.app.exit()

    @bindings.add("/")
    def _slash(event):
        # If the user has highlighted text and then types '/', wrap the
        # highlighted text in parens so it becomes the explicit numerator
        # instead of just the last atomic token.
        if buffer.selection_state is not None:
            start, end = buffer.document.selection_range()
            selected = buffer.text[start:end]
            buffer.text = buffer.text[:start] + "(" + selected + ")/" + buffer.text[end:]
            buffer.cursor_position = start + len(selected) + 3
        else:
            buffer.insert_text("/")

    @bindings.add("up")
    def _up(event):
        row = cursor_line_of(buffer)
        lines = buffer.text.split("\n")
        col = buffer.document.cursor_position_col
        if row == 0:
            return
        new_row = row - 1
        target_col = min(col, len(lines[new_row]))
        buffer.cursor_position = buffer.document.translate_row_col_to_index(
            new_row, target_col
        )

    @bindings.add("down")
    def _down(event):
        row = cursor_line_of(buffer)
        lines = buffer.text.split("\n")
        col = buffer.document.cursor_position_col
        if row >= len(lines) - 1:
            return
        new_row = row + 1
        target_col = min(col, len(lines[new_row]))
        buffer.cursor_position = buffer.document.translate_row_col_to_index(
            new_row, target_col
        )

    @bindings.add("left")
    def _left(event):
        row = cursor_line_of(buffer)
        lines = buffer.text.split("\n")
        math_start = find_math_start(lines)
        in_math_line = math_start is not None and row >= math_start
        if in_math_line:
            line = lines[row]
            col = buffer.document.cursor_position_col
            new_col = prev_stop(line, col)
            if new_col == col and col == 0:
                if row == 0:
                    return
                new_row = row - 1
                buffer.cursor_position = buffer.document.translate_row_col_to_index(
                    new_row, len(lines[new_row])
                )
                return
            buffer.cursor_position = buffer.document.translate_row_col_to_index(row, new_col)
        else:
            buffer.cursor_left()

    @bindings.add("right")
    def _right(event):
        row = cursor_line_of(buffer)
        lines = buffer.text.split("\n")
        math_start = find_math_start(lines)
        in_math_line = math_start is not None and row >= math_start
        if in_math_line:
            line = lines[row]
            col = buffer.document.cursor_position_col
            new_col = next_stop(line, col)
            if new_col == col and col == len(line):
                if row >= len(lines) - 1:
                    return
                new_row = row + 1
                buffer.cursor_position = buffer.document.translate_row_col_to_index(
                    new_row, 0
                )
                return
            buffer.cursor_position = buffer.document.translate_row_col_to_index(row, new_col)
        else:
            buffer.cursor_right()

    @bindings.add("s-left")
    def _shift_left(event):
        if buffer.selection_state is None:
            buffer.start_selection()
        buffer.cursor_left()

    @bindings.add("s-right")
    def _shift_right(event):
        if buffer.selection_state is None:
            buffer.start_selection()
        buffer.cursor_right()

    @bindings.add("backspace")
    def _backspace(event):
        buffer.delete_before_cursor(1)

    @bindings.add("delete")
    def _delete(event):
        buffer.delete(1)

    @bindings.add("enter")
    @bindings.add("c-m")
    def _enter(event):
        buffer.insert_text("\n")

    @bindings.add(Keys.Any)
    def _insert(event):
        buffer.insert_text(event.data)

    style = Style.from_dict(
        {
            "math": "#00ff5f",
            "status": "bg:#444444 #ffffff",
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