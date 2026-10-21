"""Orthogonal edge paths from Graphviz, keeping the final box positions fixed."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from clsast import Cls, ClsError
from layout import Layout, CHAR_WIDTH, PACKAGE_TAB_HEIGHT, header_height
from dotlayout import Rect, run_graphviz

Point = Tuple[float, float]
CLEARANCE = 8


@dataclass
class Route:
    source_port: Point  # relative to the source box, in [0, 1]
    target_port: Point
    points: List[Point]  # absolute layout coordinates, including both endpoints


def simplify(points: List[Point]) -> List[Point]:
    """Graphviz encodes straight orthogonal segments as repeated Bezier points."""
    result = []
    for point in points:
        if result and point == result[-1]:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            if a[0] == b[0] == point[0] or a[1] == b[1] == point[1]:
                result.pop()
            else:
                break
        result.append(point)
    return result


def connection(point: Point, rect: Rect) -> Tuple[Point, Point]:
    # Graphviz rounds widths to fractions of inches and JSON points to two decimals.
    # Snap the endpoint to the nearest actual side, retaining its position along it.
    x = min(1, max(0, (point[0] - rect.x) / rect.width))
    y = min(1, max(0, (point[1] - rect.y) / rect.height))
    distances = (abs(point[0] - rect.x), abs(point[0] - rect.x - rect.width),
                 abs(point[1] - rect.y), abs(point[1] - rect.y - rect.height))
    side = min(range(4), key=distances.__getitem__)
    if side < 2:
        x = side
    else:
        y = side - 2
    return (x, y), (rect.x + x * rect.width, rect.y + y * rect.height)


def ancestors(cls: Cls, name: str) -> frozenset:
    names = set()
    parent = cls.elements[name].parent
    while parent is not None:
        names.add(parent)
        parent = cls.elements[parent].parent
    return frozenset(names)


def padded(r: Rect, margin: float = CLEARANCE) -> Rect:
    return Rect(r.x - margin, r.y - margin, r.width + 2 * margin, r.height + 2 * margin)


def shared_body(cls: Cls, layout: Layout, source: str, target: str) -> Optional[Rect]:
    """Usable routing area in the nearest container enclosing both endpoints."""
    target_parents = ancestors(cls, target)
    parent = cls.elements[source].parent
    while parent is not None and parent not in target_parents:
        parent = cls.elements[parent].parent
    if parent is None:
        return None
    r = layout.rects[parent]
    title = header_height(cls.elements[parent])
    return Rect(r.x + CLEARANCE, r.y + title + CLEARANCE,
                r.width - 2 * CLEARANCE, r.height - title - 2 * CLEARANCE)


def inside(points: List[Point], bounds: Rect) -> bool:
    return all(bounds.x - 0.01 <= x <= bounds.x + bounds.width + 0.01
               and bounds.y - 0.01 <= y <= bounds.y + bounds.height + 0.01 for x, y in points)


def obstacles(cls: Cls, layout: Layout, allowed: frozenset) -> Dict[str, Rect]:
    boxes = {}
    needs_padding = set()

    def visit(element):
        r = layout.rects[element.id]
        if not element.is_container:
            # Preserve exact endpoint geometry; padding can move a Graphviz port
            # beyond a real corner and turn a snapped segment into a diagonal.
            boxes[element.id] = r
            return
        if element.id not in allowed:
            boxes[element.id] = r
            needs_padding.add(element.id)
            return  # A solid unrelated container also covers all its children.
        w = min(r.width, max(70, len(element.label) * CHAR_WIDTH + 24))
        x = r.x if element.kind == 'package' else r.x + (r.width - w) / 2
        name = '$title_' + element.id
        boxes[name] = Rect(x, r.y, w, header_height(element))
        needs_padding.add(name)
        for child in element.children:
            visit(child)

    for root in cls.roots:
        visit(root)
    result = dict(boxes)
    for name in sorted(needs_padding):
        r = boxes[name]
        # Inflated obstacles must not overlap: Graphviz otherwise falls back to
        # splines. Leave a gap even when the existing layout is tightly packed.
        gaps = [max(r.x - b.x - b.width, b.x - r.x - r.width,
                    r.y - b.y - b.height, b.y - r.y - r.height, 0)
                for other, b in boxes.items() if other != name]
        margin = min(CLEARANCE, max(0, (min(gaps) - 1) / 2)) if gaps else CLEARANCE
        result[name] = padded(r, margin)
    return result


def hits(a: Point, b: Point, r: Rect) -> bool:
    """Intersection with an obstacle's interior; touching its padded edge is safe."""
    eps = 0.01
    if abs(a[0] - b[0]) < eps:
        return (r.x + eps < a[0] < r.x + r.width - eps
                and max(a[1], b[1]) > r.y + eps and min(a[1], b[1]) < r.y + r.height - eps)
    if abs(a[1] - b[1]) < eps:
        return (r.y + eps < a[1] < r.y + r.height - eps
                and max(a[0], b[0]) > r.x + eps and min(a[0], b[0]) < r.x + r.width - eps)
    return True


def border_runs(points, cls: Cls, layout: Layout, allowed: frozenset):
    runs = []
    for name in sorted(allowed):
        r = layout.rects[name]
        top = r.y + (PACKAGE_TAB_HEIGHT if cls.elements[name].kind == 'package' else 0)
        for index, (a, b) in enumerate(zip(points, points[1:])):
            for axis, borders, start, end in ((0, (r.x, r.x + r.width), top, r.y + r.height),
                                               (1, (top, r.y + r.height), r.x, r.x + r.width)):
                other = 1 - axis
                if (abs(a[axis] - b[axis]) < 0.01
                        and min(max(a[other], b[other]), end)
                        - max(min(a[other], b[other]), start) > 0.01):
                    for border in borders:
                        if abs(a[axis] - border) < CLEARANCE - 0.01:
                            runs.append((index, axis, border))
    return runs


def clear_borders(route: Route, relation, cls: Cls, layout: Layout, allowed, boxes) -> Route:
    # Crossing an ancestor boundary is valid; following that boundary is unreadable.
    # Only accept small offsets that clear every obstacle and reduce border overlaps.
    boxes = dict(boxes)
    for name in (relation.source, relation.target):
        boxes[name] = layout.rects[name]
    points = route.points
    bounds = shared_body(cls, layout, relation.source, relation.target)
    if bounds is not None:
        # Pull detours into the container's free perimeter corridor. Clamping
        # coordinates preserves orthogonality; collision checks prevent shortcuts
        # through children, titles, or unrelated containers.
        candidate = simplify([(min(max(x, bounds.x), bounds.x + bounds.width),
                               min(max(y, bounds.y), bounds.y + bounds.height)) for x, y in points])
        if (bounds.width <= 0 or bounds.height <= 0
                or candidate[0] != points[0] or candidate[-1] != points[-1]
                or any(hits(a, b, r) for a, b in zip(candidate, candidate[1:]) for r in boxes.values())):
            raise ClsError('Not enough room to keep the connector inside its shared container',
                           relation.line_number)
        points = candidate
    while True:
        runs = border_runs(points, cls, layout, allowed)
        if not runs:
            source_port, points[0] = connection(points[0], layout.rects[relation.source])
            target_port, points[-1] = connection(points[-1], layout.rects[relation.target])
            return Route(source_port, target_port, points)
        for index, axis, border in runs:
            for offset in (-CLEARANCE, CLEARANCE, -2 * CLEARANCE, 2 * CLEARANCE):
                candidate = list(points)
                for i in (index, index + 1):
                    p = list(candidate[i])
                    p[axis] = border + offset
                    candidate[i] = tuple(p)
                # Moving an end segment must keep its endpoint on the actual box.
                if bounds is not None and not inside(candidate, bounds):
                    continue
                endpoints = [(candidate[0], layout.rects[relation.source]),
                             (candidate[-1], layout.rects[relation.target])]
                if any(max(abs(a - b) for a, b in zip(p, connection(p, r)[1])) > 0.01
                       for p, r in endpoints):
                    continue
                if any(hits(a, b, r) for a, b in zip(candidate, candidate[1:]) for r in boxes.values()):
                    continue
                candidate = simplify(candidate)
                if len(border_runs(candidate, cls, layout, allowed)) < len(runs):
                    points = candidate
                    break
            else:
                continue
            break
        else:
            raise ClsError('Not enough clearance to route away from container borders',
                           relation.line_number)


def route_group(cls: Cls, layout: Layout, allowed: frozenset, indices) -> Dict[int, Route]:

    # -n2 routes edges only; notranslate preserves the supplied coordinates.
    # Only containers holding an endpoint are transparent in this routing group.
    out = ['digraph g {',
           'graph [splines=ortho, notranslate=true, overlap=true];',
           'node [shape=box, fixedsize=true, label="", margin=0];',
           'edge [arrowhead=none, arrowtail=none];']
    def box(name: str, r: Rect) -> None:
        out.append(f'"{name}" [pos="{r.x + r.width / 2},{layout.height - r.y - r.height / 2}!", '
                   f'width={r.width / 72}, height={r.height / 72}];')

    boxes = obstacles(cls, layout, allowed)
    for name, rect in boxes.items():
        box(name, rect)
    for index in indices:
        relation = cls.relations[index]
        source, target = f'"{relation.source}"', f'"{relation.target}"'
        if any(relation.source in g.names and relation.target in g.names for g in cls.horizontal):
            rightward = layout.rects[relation.source].x < layout.rects[relation.target].x
            source += ':e' if rightward else ':w'
            target += ':w' if rightward else ':e'
        out.append(f'{source} -> {target} [id="route_{index}"];')
    out.append('}')
    graph = run_graphviz('\n'.join(out), 'neato', ('-n2',))
    edges = {e['id']: e for e in graph.get('edges', [])}

    routes = {}
    for index in indices:
        relation = cls.relations[index]
        edge = edges.get(f'route_{index}', {})
        points = simplify([(x, layout.height - y)
                           for op in edge.get('_draw_', []) if op['op'] == 'b'
                           for x, y in op['points']])
        if len(points) < 2:
            raise ClsError(f'Graphviz could not route {relation.source} to {relation.target}',
                           relation.line_number)
        source_port, points[0] = connection(points[0], layout.rects[relation.source])
        target_port, points[-1] = connection(points[-1], layout.rects[relation.target])
        if any(abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
               for a, b in zip(points, points[1:])):
            raise ClsError('Graphviz did not return an orthogonal route; check for overlapping boxes',
                           relation.line_number)
        route = Route(source_port, target_port, points)
        routes[index] = clear_borders(route, relation, cls, layout, allowed, boxes)
    return routes


def route_edges(cls: Cls, layout: Layout) -> Dict[int, Route]:
    groups = {}
    for index, relation in enumerate(cls.relations):
        allowed = ancestors(cls, relation.source) | ancestors(cls, relation.target)
        groups.setdefault(allowed, []).append(index)
    routes = {}
    for allowed, indices in groups.items():
        routes.update(route_group(cls, layout, allowed, indices))
    return routes
