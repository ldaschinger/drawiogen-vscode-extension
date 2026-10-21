"""Measure FSM text with Graphviz's local fonts, without a browser dependency."""
import html
import math
from typing import Iterable, Tuple

from dotlayout import run_graphviz

FONT_FAMILY = 'Arial'
Request = Tuple[str, int, bool]
_widths = {}


def measure_texts(requests: Iterable[Request]) -> None:
    missing = list(dict.fromkeys(request for request in requests if request not in _widths))
    if not missing:
        return
    lines = ['digraph text { node [shape=plain];']
    for index, (text, size, bold) in enumerate(missing):
        # Nonbreaking spaces preserve the indentation that draw.io renders as nbsp.
        # Graphviz's HTML parser rejects an isolated closing bracket unless
        # encoded; measuring individual glyphs can encounter exactly that case.
        value = html.escape(text).replace(']', '&#93;').replace(' ', '&#160;') or '&#160;'
        if bold:
            value = '<B>' + value + '</B>'
        lines.append(f't{index} [label=<<FONT FACE="{FONT_FAMILY}" '
                     f'POINT-SIZE="{size}">{value}</FONT>>];')
    lines.append('}')
    graph = run_graphviz('\n'.join(lines))
    for obj in graph.get('objects', []):
        request = missing[int(obj['name'][1:])]
        _widths[request] = 0 if not request[0] else math.ceil(float(obj['width']) * 72)


def text_width(text: str, size: int, bold: bool = False) -> float:
    exact = _widths.get((text, size, bold))
    if exact is not None:
        return exact
    # Wrapped lines are assembled from premeasured words and spaces. Extra
    # state padding absorbs font rounding and kerning differences at word joins.
    return sum(_widths[(word, size, bold)] for word in text.split(' ') if word) + text.count(' ') * _widths[(' ', size, bold)]


def wrap_measured(text: str, width: float, size: int) -> list:
    """Wrap a label in pixels, splitting overlong identifiers without truncation."""
    words = text.split()
    requests = [(text, size, False), (' ', size, False)]
    requests += [(word, size, False) for word in words]
    requests += [(char, size, False) for char in set(text) if not char.isspace()]
    measure_texts(requests)
    if text_width(text, size) <= width:
        return [text]
    pieces = []
    for word in words:
        word_width = text_width(word, size)
        if word_width <= width:
            pieces.append((word, word_width))
            continue
        part, part_width = '', 0
        for char in word:
            char_width = text_width(char, size)
            if part and part_width + char_width > width:
                pieces.append((part, part_width))
                part, part_width = '', 0
            part += char
            part_width += char_width
        if part:
            pieces.append((part, part_width))
    result, line, used_width = [], '', 0
    space = text_width(' ', size)
    for piece, piece_width in pieces:
        gap = space if line else 0
        if line and used_width + gap + piece_width > width:
            result.append(line)
            line, used_width, gap = '', 0, 0
        line += (' ' if line else '') + piece
        used_width += gap + piece_width
    return result + [line]
