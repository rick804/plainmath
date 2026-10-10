#!/usr/bin/env python3

"""
plainmath — terminal-native structured math editor.

PRE-RENDER contains the actual editable source.

RENDERED contains the mathematical representation.

Fractions:

    a/b              -> {a/b}
    a/b+c            -> {a/b+c}
    a+b/c+d          -> {a+b/c+d}
    a+b/c+d/e        -> a+{b/c+{d/e}}

The source cursor is authoritative.

Every source insertion position is reachable with the arrow keys,
including positions immediately before and after structural braces.
"""

import sys

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from prompt_toolkit.layout.containers import (
    HSplit,
    Window,
)

from prompt_toolkit.layout.controls import (
    FormattedTextControl,
    UIContent,
    UIControl,
)

from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.screen import Point
from prompt_toolkit.styles import Style

from engine import (
    render_line,
    locate_cursor,
    next_stop,
    prev_stop,
    insert_fraction,
    make_fraction_from_selection,
    collapse_fraction,
)


PLAINMATH_FLAG = "PLAINMATH"


# ==========================================================================
# Helpers
# ==========================================================================

def find_math_start(lines):

    for i, line in enumerate(lines):

        if line.strip().upper() == PLAINMATH_FLAG:
            return i + 1

    return None


def cursor_line_of(buffer):

    return buffer.document.cursor_position_row


def cursor_col_of(buffer):

    return buffer.document.cursor_position_col


def set_cursor_row_col(
    buffer,
    row,
    col,
):

    lines = buffer.text.split("\n")

    if not lines:
        return

    row = max(
        0,
        min(
            row,
            len(lines) - 1,
        ),
    )

    col = max(
        0,
        min(
            col,
            len(lines[row]),
        ),
    )

    buffer.cursor_position = (
        buffer.document
        .translate_row_col_to_index(
            row,
            col,
        )
    )


# ==========================================================================
# PRE-RENDER CONTROL
# ==========================================================================

class SourceEditorControl(UIControl):

    def __init__(self, buffer):

        self.buffer = buffer

    def is_focusable(self):

        return True

    def create_content(
        self,
        width,
        height,
    ):

        text = self.buffer.text
        lines = text.split("\n")

        if not lines:
            lines = [""]

        cursor_row = (
            self.buffer.document
            .cursor_position_row
        )

        cursor_col = (
            self.buffer.document
            .cursor_position_col
        )

        # Always clamp the cursor against the actual source line.
        cursor_row = max(
            0,
            min(
                cursor_row,
                len(lines) - 1,
            ),
        )

        cursor_col = max(
            0,
            min(
                cursor_col,
                len(lines[cursor_row]),
            ),
        )

        output = []

        for line in lines:

            output.append([
                (
                    "class:source",
                    line,
                )
            ])

        # Point.x is the exact character insertion position.
        cursor_point = Point(
            x=cursor_col,
            y=cursor_row,
        )

        return UIContent(
            get_line=lambda i: output[i],
            line_count=len(output),
            cursor_position=cursor_point,
            show_cursor=True,
        )


# ==========================================================================
# RENDERED CONTROL
# ==========================================================================

class RenderedMathControl(UIControl):

    def __init__(self, buffer):

        self.buffer = buffer

    def is_focusable(self):

        return False

    def create_content(
        self,
        width,
        height,
    ):

        text = self.buffer.text
        lines = text.split("\n")

        if not lines:
            lines = [""]

        cursor_row = (
            self.buffer.document
            .cursor_position_row
        )

        cursor_col = (
            self.buffer.document
            .cursor_position_col
        )

        cursor_row = max(
            0,
            min(
                cursor_row,
                len(lines) - 1,
            ),
        )

        cursor_col = max(
            0,
            min(
                cursor_col,
                len(lines[cursor_row]),
            ),
        )

        output = []
        cursor_point = None

        math_start = find_math_start(
            lines
        )

        for source_row, line in enumerate(lines):

            in_math = (
                math_start is not None
                and source_row >= math_start
            )

            # --------------------------------------------------------------
            # Plain text.
            # --------------------------------------------------------------

            if not in_math:

                rendered_line = line

                output.append([
                    (
                        "class:rendered",
                        rendered_line,
                    )
                ])

                if source_row == cursor_row:

                    cursor_point = Point(
                        x=min(
                            cursor_col,
                            len(rendered_line),
                        ),
                        y=len(output) - 1,
                    )

                continue

            # --------------------------------------------------------------
            # Mathematical line.
            # --------------------------------------------------------------

            try:

                rendered_lines = render_line(
                    line
                )

                if not rendered_lines:
                    rendered_lines = [""]

            except Exception:

                rendered_lines = [line]

            visual_row = None
            visual_col = None

            if source_row == cursor_row:

                try:

                    visual_row, visual_col = locate_cursor(
                        line,
                        cursor_col,
                    )

                except Exception:

                    visual_row = 0

                    visual_col = min(
                        cursor_col,
                        len(rendered_lines[0]),
                    )

            # Clamp rendered cursor coordinates too.
            if visual_row is not None:

                visual_row = max(
                    0,
                    min(
                        visual_row,
                        len(rendered_lines) - 1,
                    ),
                )

                visual_col = max(
                    0,
                    min(
                        visual_col,
                        len(rendered_lines[visual_row]),
                    ),
                )

            for rendered_row, rendered_line in enumerate(
                rendered_lines
            ):

                output.append([
                    (
                        "class:rendered",
                        rendered_line,
                    )
                ])

                if (
                    source_row == cursor_row
                    and rendered_row == visual_row
                ):

                    cursor_point = Point(
                        x=min(
                            visual_col,
                            len(rendered_line),
                        ),
                        y=len(output) - 1,
                    )

        if not output:

            output = [
                [
                    (
                        "class:rendered",
                        "",
                    )
                ]
            ]

        if cursor_point is None:

            cursor_point = Point(
                x=0,
                y=0,
            )

        return UIContent(
            get_line=lambda i: output[i],
            line_count=len(output),
            cursor_position=cursor_point,
            show_cursor=True,
        )


# ==========================================================================
# Application
# ==========================================================================

def make_app(filepath):

    with open(
        filepath,
        "r",
        encoding="utf-8",
    ) as f:

        text = f.read()

    buffer = Buffer(
        document=Document(
            text,
            0,
        ),
        multiline=True,
    )

    source_window = Window(
        content=SourceEditorControl(
            buffer
        ),
        wrap_lines=False,
        height=None,
    )

    rendered_window = Window(
        content=RenderedMathControl(
            buffer
        ),
        wrap_lines=False,
        height=None,
    )

    source_header = Window(
        content=FormattedTextControl(
            lambda: " PRE-RENDER"
        ),
        height=1,
        style="class:header",
    )

    rendered_header = Window(
        content=FormattedTextControl(
            lambda: " RENDERED"
        ),
        height=1,
        style="class:header",
    )

    status_window = Window(
        content=FormattedTextControl(
            lambda:
                f" {filepath}   "
                f"Ctrl+S save   "
                f"Ctrl+Q save + quit   "
                f"/ fraction   "
                f"Shift+Arrow select"
        ),
        height=1,
        style="class:status",
    )

    root_container = HSplit([
        source_header,
        source_window,
        rendered_header,
        rendered_window,
        status_window,
    ])

    bindings = KeyBindings()

    # ======================================================================
    # Save
    # ======================================================================

    @bindings.add("c-s")
    def _save(event):

        with open(
            filepath,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(buffer.text)

    # ======================================================================
    # Save + quit
    # ======================================================================

    @bindings.add("c-q")
    def _quit(event):

        with open(
            filepath,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(buffer.text)

        event.app.exit()

    # ======================================================================
    # Fraction
    # ======================================================================

    @bindings.add("/")
    def _slash(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.insert_text("/")
            return

        # --------------------------------------------------------------
        # Selection.
        # --------------------------------------------------------------

        if buffer.selection_state is not None:

            start, end = (
                buffer.document
                .selection_range()
            )

            line_start = (
                buffer.document
                .translate_row_col_to_index(
                    row,
                    0,
                )
            )

            line_end = (
                line_start
                + len(lines[row])
            )

            selected = buffer.text[
                start:end
            ]

            if (
                "\n" not in selected
                and start >= line_start
                and end <= line_end
            ):

                local_start = (
                    start - line_start
                )

                local_end = (
                    end - line_start
                )

                line = lines[row]

                new_line, new_col = (
                    make_fraction_from_selection(
                        line,
                        local_start,
                        local_end,
                    )
                )

                lines[row] = new_line

                buffer.text = "\n".join(
                    lines
                )

                set_cursor_row_col(
                    buffer,
                    row,
                    new_col,
                )

                return

        # --------------------------------------------------------------
        # Previous operand.
        # --------------------------------------------------------------

        line = lines[row]
        col = cursor_col_of(buffer)

        new_line, new_col = insert_fraction(
            line,
            col,
        )

        lines[row] = new_line

        buffer.text = "\n".join(
            lines
        )

        set_cursor_row_col(
            buffer,
            row,
            new_col,
        )

    # ======================================================================
    # Enter
    # ======================================================================

    @bindings.add("enter")
    @bindings.add("c-m")
    def _enter(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        current_line = lines[row]

        if current_line.strip() == "exit":

            del lines[row]

            if not lines:
                lines = [""]

            buffer.text = "\n".join(
                lines
            )

            event.app.exit()
            return

        buffer.insert_text("\n")

    # ======================================================================
    # Left
    # ======================================================================

    @bindings.add("left")
    def _left(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.cursor_left()
            return

        line = lines[row]
        col = cursor_col_of(buffer)

        new_col = prev_stop(
            line,
            col,
        )

        if (
            new_col == col
            and col == 0
        ):

            if row == 0:
                return

            new_row = row - 1

            set_cursor_row_col(
                buffer,
                new_row,
                len(lines[new_row]),
            )

            return

        set_cursor_row_col(
            buffer,
            row,
            new_col,
        )

    # ======================================================================
    # Right
    # ======================================================================

    @bindings.add("right")
    def _right(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.cursor_right()
            return

        line = lines[row]
        col = cursor_col_of(buffer)

        new_col = next_stop(
            line,
            col,
        )

        if (
            new_col == col
            and col == len(line)
        ):

            if row >= len(lines) - 1:
                return

            new_row = row + 1

            set_cursor_row_col(
                buffer,
                new_row,
                0,
            )

            return

        set_cursor_row_col(
            buffer,
            row,
            new_col,
        )

    # ======================================================================
    # Shift + Left
    # ======================================================================

    @bindings.add("s-left")
    def _shift_left(event):

        if buffer.selection_state is None:
            buffer.start_selection()

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.cursor_left()
            return

        col = cursor_col_of(buffer)

        new_col = prev_stop(
            lines[row],
            col,
        )

        set_cursor_row_col(
            buffer,
            row,
            new_col,
        )

    # ======================================================================
    # Shift + Right
    # ======================================================================

    @bindings.add("s-right")
    def _shift_right(event):

        if buffer.selection_state is None:
            buffer.start_selection()

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.cursor_right()
            return

        col = cursor_col_of(buffer)

        new_col = next_stop(
            lines[row],
            col,
        )

        set_cursor_row_col(
            buffer,
            row,
            new_col,
        )

    # ======================================================================
    # Up
    # ======================================================================

    @bindings.add("up")
    def _up(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        if row == 0:
            return

        col = cursor_col_of(buffer)

        new_row = row - 1

        target_col = min(
            col,
            len(lines[new_row]),
        )

        set_cursor_row_col(
            buffer,
            new_row,
            target_col,
        )

    # ======================================================================
    # Down
    # ======================================================================

    @bindings.add("down")
    def _down(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        if row >= len(lines) - 1:
            return

        col = cursor_col_of(buffer)

        new_row = row + 1

        target_col = min(
            col,
            len(lines[new_row]),
        )

        set_cursor_row_col(
            buffer,
            new_row,
            target_col,
        )

    # ======================================================================
    # Backspace
    # ======================================================================

    @bindings.add("backspace")
    def _backspace(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.delete_before_cursor(1)
            return

        line = lines[row]
        col = cursor_col_of(buffer)

        # --------------------------------------------------------------
        # There are deliberately NO structural-brace guards here.
        #
        # Every source character is deletable.
        #
        # This fixes the old behavior where:
        #
        #     {|
        #
        # could not delete {
        #
        # and where some closing braces became effectively immutable.
        # --------------------------------------------------------------

        if col > 0:

            buffer.delete_before_cursor(1)

    # ======================================================================
    # Delete
    # ======================================================================

    @bindings.add("delete")
    def _delete(event):

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.delete(1)
            return

        # --------------------------------------------------------------
        # Keep the slash-boundary collapse as the one special structural
        # delete operation.
        # --------------------------------------------------------------

        line = lines[row]
        col = cursor_col_of(buffer)

        collapsed = collapse_fraction(
            line,
            col,
        )

        if collapsed is not None:

            new_line, new_col = collapsed

            lines[row] = new_line

            buffer.text = "\n".join(
                lines
            )

            set_cursor_row_col(
                buffer,
                row,
                new_col,
            )

            return

        # --------------------------------------------------------------
        # Everything else, including { and }, is normally deletable.
        # --------------------------------------------------------------

        if col < len(line):

            buffer.delete(1)

    # ======================================================================
    # Normal insertion
    # ======================================================================

    @bindings.add(Keys.Any)
    def _insert(event):

        text = event.data

        if not text:
            return

        row = cursor_line_of(buffer)

        lines = buffer.text.split("\n")

        math_start = find_math_start(
            lines
        )

        in_math = (
            math_start is not None
            and row >= math_start
        )

        if not in_math:

            buffer.insert_text(text)
            return

        # --------------------------------------------------------------
        # IMPORTANT:
        #
        # Operators do not automatically escape fractions.
        #
        # Example:
        #
        #     {b/c|}
        #
        # typing +
        #
        #     {b/c+}
        #
        # Moving right once gives:
        #
        #     {b/c}|
        #
        # and typing + then produces:
        #
        #     {b/c}+
        # --------------------------------------------------------------

        buffer.insert_text(text)

    # ======================================================================
    # Style
    # ======================================================================

    style = Style.from_dict({
        "header": "bold",
        "source": "",
        "rendered": "",
        "status": "bg:#444444 #ffffff",
    })

    return Application(
        layout=Layout(
            root_container,
            focused_element=source_window,
        ),
        key_bindings=bindings,
        style=style,
        full_screen=True,
    )


# ==========================================================================
# Main
# ==========================================================================

def main():

    if len(sys.argv) != 2:

        print(
            "Usage: python plainmath.py <file>"
        )

        sys.exit(1)

    try:

        app = make_app(
            sys.argv[1]
        )

        app.run()

    except SystemExit:

        raise

    except BaseException:

        import traceback

        traceback.print_exc()

        input(
            "\n[plainmath crashed — press Enter to close] "
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
