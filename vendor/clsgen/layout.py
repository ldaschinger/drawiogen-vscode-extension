import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

from dotlayout import GNode, GEdge, Rect, layout_graph, CLUSTER_MARGIN

from clsast import Cls, ClsError, Element, top_level_element

# Conservative estimate for 12 px bold labels, including sans-serif font fallbacks.
CHAR_WIDTH = 8
ROW_HEIGHT = 20
DIVIDER_HEIGHT = 8
HEADER_HEIGHT = 26
HEADER_STEREOTYPE_HEIGHT = 42
PACKAGE_TAB_HEIGHT = 24
MIN_WIDTH = 160
COMPONENT_HEIGHT = 60
COMPONENT_LABEL_PADDING = 68  # space on both sides keeps text clear of the corner icon
EMPTY_COMPARTMENT_HEIGHT = 30
EDGE_LABEL_WRAP = 28
ARRANGEMENT_GAP = 72

# Arrows that point from child/implementor to parent: lay them out parent-first.
REVERSED_FOR_LAYOUT = ('--|>', '..|>')


@dataclass
class Layout:
    rects: Dict[str, Rect]      # absolute, top-left based
    width: float
    height: float


def attribute_rows(element: Element):
    if element.kind == 'enum':
        return list(element.members)
    return [m for m in element.members if not m.is_method]


def method_rows(element: Element):
    return [m for m in element.members if m.is_method]


def header_height(element: Element) -> int:
    return HEADER_STEREOTYPE_HEIGHT if element.stereotype else HEADER_HEIGHT


def size_of(element: Element) -> Tuple[float, float]:
    texts = [element.label] + [f'{m.visibility} {m.text}' for m in element.members]
    if element.stereotype:
        texts.append(f'«{element.stereotype}»')
    width = max(MIN_WIDTH, round(max(len(t) for t in texts) * CHAR_WIDTH + 24))

    if element.kind == 'component':
        return max(width, round(len(element.label) * CHAR_WIDTH + COMPONENT_LABEL_PADDING)), COMPONENT_HEIGHT

    if not element.members:
        return width, max(COMPONENT_HEIGHT, header_height(element) + EMPTY_COMPARTMENT_HEIGHT)

    height = header_height(element) + ROW_HEIGHT * len(attribute_rows(element))
    if element.kind != 'enum':
        height += DIVIDER_HEIGHT + ROW_HEIGHT * len(method_rows(element))
    return width, max(height, COMPONENT_HEIGHT - 20)


def build_gnode(element: Element) -> GNode:
    if element.is_container:
        children = [build_gnode(c) for c in element.children]
        # Match sibling boxes before layout so spacing and container bounds include
        # the largest label and body. Nested containers size themselves independently.
        boxes = [child for child in children if not child.is_container]
        if boxes:
            width = max(child.width for child in boxes)
            height = max(child.height for child in boxes)
            for child in boxes:
                child.width, child.height = width, height
        return GNode(element.id, label=element.label, is_container=True,
                     children=children, top_row=element.top_row.names if element.top_row else [])
    w, h = size_of(element)
    return GNode(element.id, w, h)


def wrap_label(label: str) -> List[str]:
    return textwrap.wrap(label, EDGE_LABEL_WRAP) if label else []


def layout_cls(cls: Cls) -> Layout:
    roots = [build_gnode(e) for e in cls.roots]
    edges = []
    for r in cls.relations:
        source, target = r.source, r.target
        if r.arrow in REVERSED_FOR_LAYOUT:
            source, target = target, source
        edges.append(GEdge(source, target, wrap_label(r.label)))

    rects, width, height = layout_graph(roots, edges, cls.direction)
    center_component_contents(cls, rects)
    if cls.arrangement:
        width, height = arrange_roots(cls, rects)
    if cls.horizontal or cls.same_size:
        align_horizontal(cls, rects)
        equalize_sizes(cls, rects)
        width, height = arrange_roots(cls, rects)
    return Layout(rects, width, height)


def translate(element: Element, rects: Dict[str, Rect], dx: float, dy: float) -> None:
    rect = rects[element.id]
    rect.x += dx
    rect.y += dy
    for child in element.children:
        translate(child, rects, dx, dy)


def center_component_contents(cls: Cls, rects: Dict[str, Rect]) -> None:
    """Center child groups in the component body, below its reserved title area."""
    # Inner components first; moving their parent later preserves their own centering.
    for element in reversed(list(cls.elements.values())):
        if element.kind != 'component' or not element.is_container:
            continue
        parent = rects[element.id]
        children = [rects[c.id] for c in element.children]
        left = min(c.x for c in children)
        right = max(c.x + c.width for c in children)
        top = min(c.y for c in children)
        bottom = max(c.y + c.height for c in children)
        body_top = parent.y + header_height(element)
        dx = parent.x + parent.width / 2 - (left + right) / 2
        dy = (body_top + parent.y + parent.height) / 2 - (top + bottom) / 2
        for child in element.children:
            translate(child, rects, dx, dy)


def arrange_roots(cls: Cls, rects: Dict[str, Rect]) -> Tuple[float, float]:
    """Place whole top-level subtrees in a row/column, preserving their inner layout."""
    x = y = width = height = 0
    for element in cls.roots:
        rect = rects[element.id]
        translate(element, rects, x - rect.x, y - rect.y)
        width = max(width, rect.x + rect.width)
        height = max(height, rect.y + rect.height)
        if cls.arrangement == 'LR':
            x += rect.width + ARRANGEMENT_GAP
        else:
            y += rect.height + ARRANGEMENT_GAP
    return width, height


def center_y(rect: Rect) -> float:
    return rect.y + rect.height / 2


def align_horizontal(cls: Cls, rects: Dict[str, Rect]) -> None:
    for group in cls.horizontal:
        target_y = max(center_y(rects[n]) for n in group.names)
        for name in group.names:
            dy = target_y - center_y(rects[name])
            if dy == 0:
                continue
            root = top_level_element(cls, name)
            # Move the whole branch so interfaces, members, and inheritance stay together.
            branch = cls.elements[name]
            while branch.parent != root.id:
                branch = cls.elements[branch.parent]
            branch_y = rects[branch.id].y
            # Lower siblings move too, leaving room rather than introducing overlaps.
            for child in root.children:
                if rects[child.id].y >= branch_y:
                    translate(child, rects, 0, dy)
            root_rect = rects[root.id]
            root_rect.height = max(root_rect.height,
                                   max(rects[c.id].y + rects[c.id].height for c in root.children)
                                   - root_rect.y + CLUSTER_MARGIN)

    for group in cls.horizontal:
        centers = [center_y(rects[n]) for n in group.names]
        if max(centers) - min(centers) > 0.01:
            raise ClsError('Conflicting align-horizontal groups; use one group for elements '
                           'that should share a horizontal line', group.line_number)


def equalize_sizes(cls: Cls, rects: Dict[str, Rect]) -> None:
    # Repeated propagation also handles overlapping groups such as A B and B C.
    changed = True
    while changed:
        changed = False
        for group in cls.same_size:
            width = max(rects[n].width for n in group.names)
            height = max(rects[n].height for n in group.names)
            for name in group.names:
                rect = rects[name]
                if (rect.width, rect.height) != (width, height):
                    rect.width, rect.height = width, height
                    changed = True
