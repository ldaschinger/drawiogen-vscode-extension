"""Keep orthogonal Graphviz edge geometry and center captions on its segments.

The shared layout helper only returns node rectangles. FSM edges must keep their
routes too: asking draw.io to route them again loses parallel and return lanes.
"""
from dataclasses import dataclass
from collections import deque
import html
import json
import math
from typing import List, Optional, Tuple

from dotlayout import run_graphviz
from diagramerror import DiagramError
from textmetrics import measure_texts, text_width

Point = Tuple[float, float]
EDGE_FONT_SIZE = 11
EDGE_FONT_FAMILY = 'Arial'
LABEL_PADDING = 8
INITIAL_ARROW_LENGTH = 32


@dataclass
class EdgeRoute:
    points: List[Point]
    label: Optional[Point] = None


def dot_label(lines: List[str]) -> str:
    if not any(lines):
        return '""'
    text = '<BR/>'.join(html.escape(line) or ' ' for line in lines)
    return ('<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
            f'CELLPADDING="{LABEL_PADDING}"><TR><TD>{text}</TD></TR></TABLE>>')


def simplify(points: List[Point]) -> List[Point]:
    """Remove repeated/collinear Bezier control points from dot's orthogonal output."""
    result = []
    for point in points:
        if result and math.dist(result[-1], point) < 0.05:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            length = math.dist(a, point)
            if not length:
                break
            distance = abs((b[0] - a[0]) * (point[1] - a[1])
                           - (b[1] - a[1]) * (point[0] - a[0])) / length
            forward = ((b[0] - a[0]) * (point[0] - b[0])
                       + (b[1] - a[1]) * (point[1] - b[1])) >= 0
            if distance > 0.15 or not forward:
                break
            result.pop()
        result.append(point)
    return result


def midpoint(points: List[Point]) -> Point:
    """Draw.io places an edge's default label halfway along its total length."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) / 2
    for a, b, length in zip(points, points[1:], lengths):
        if length and remaining <= length:
            ratio = remaining / length
            return a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])
        remaining -= length
    return points[-1]


def label_size(lines: List[str]) -> Point:
    return (max(text_width(line, EDGE_FONT_SIZE) for line in lines) + 2 * LABEL_PADDING,
            len(lines) * 13 + 2 * LABEL_PADDING)


def label_candidates(points: List[Point], preferred: Point, size: Point, obstacles) -> List[Point]:
    """Find caption positions on straight segments, including space-saving alternatives."""
    candidates = []
    for a, b in zip(points, points[1:]):
        vertical = abs(a[0] - b[0]) < 0.01
        axis = 1 if vertical else 0
        lo, hi = sorted((a[axis], b[axis]))
        margin = size[axis] / 2
        if hi - lo < 2 * margin:
            continue
        intervals = [(lo + margin, hi - margin)]
        cross_axis = 1 - axis
        for box in obstacles:
            # Expand obstacles by half the caption size and 4 px clearance.
            if not (box[cross_axis] - size[cross_axis] / 2 - 4 < a[cross_axis]
                    < box[cross_axis + 2] + size[cross_axis] / 2 + 4):
                continue
            blocked_lo = box[axis] - margin - 4
            blocked_hi = box[axis + 2] + margin + 4
            available = []
            for start, end in intervals:
                if blocked_hi <= start or blocked_lo >= end:
                    available.append((start, end))
                else:
                    if start < blocked_lo:
                        available.append((start, blocked_lo))
                    if blocked_hi < end:
                        available.append((blocked_hi, end))
            intervals = available
        for start, end in intervals:
            value = min(end, max(start, preferred[axis]))
            for coordinate in (value, start, end, (start + end) / 2):
                anchor = (a[0], coordinate) if vertical else (coordinate, a[1])
                candidates.append((math.dist(anchor, preferred), anchor))
    return list(dict.fromkeys(anchor for _, anchor in sorted(candidates)))


def place_route_labels(routes, labels, obstacles):
    """Try alternative caption positions before requesting a larger state layout."""
    jobs = [(index, label_size(lines)) for index, lines in enumerate(labels) if any(lines)]
    positions = {}
    attempts = 0
    occupied = list(obstacles)

    def place(job):
        nonlocal attempts
        if job == len(jobs):
            return True
        index, size = jobs[job]
        route = routes[index]
        preferred = route.label or midpoint(route.points)
        for anchor in label_candidates(route.points, preferred, size, occupied):
            attempts += 1
            if attempts > 1024:
                return False
            x, y = anchor
            occupied.append((x - size[0] / 2, y - size[1] / 2,
                             x + size[0] / 2, y + size[1] / 2))
            positions[index] = anchor
            if place(job + 1):
                return True
            occupied.pop()
            positions.pop(index)
        return False

    return positions if place(0) else None


def compact_initial_arrow(nodes, transitions, routes, labels):
    """Move the start marker close to its target without moving the state graph."""
    for transition, route, lines in zip(transitions, routes, labels):
        node = nodes[transition.source]
        if node.kind != 'initial':
            continue
        a, end = route.points[-2:]
        axis = 1 if abs(a[0] - end[0]) < 0.01 else 0
        length = INITIAL_ARROW_LENGTH
        if any(lines):
            length = max(length, label_size(lines)[axis] + 2 * LABEL_PADDING)
        # Only trim a free terminal segment. Retain a short existing route or
        # a bend whose final leg has insufficient room for the marker.
        available = abs(end[axis] - a[axis])
        if available <= length or (len(route.points) > 2
                                  and available < length + (node.width if axis == 0 else node.height)):
            continue
        sign = 1 if end[axis] > a[axis] else -1
        start = list(end)
        start[axis] -= sign * length
        center = list(start)
        center[axis] -= sign * (node.width if axis == 0 else node.height) / 2
        node.x, node.y = center[0] - node.width / 2, center[1] - node.height / 2
        route.points = [tuple(start), end]
        if any(lines):
            route.label = midpoint(route.points)


def route_graph(nodes, transitions, labels, direction, spacing=50.4, _label_attempt=0):
    # Orthogonal dot routes do not support ordinary edge-label placement. Use
    # external labels as placement references, reserving their space along the
    # rank direction before centering the exported captions on the final routes.
    visible_labels = [lines for lines in labels if any(lines)]
    measure_texts((line, EDGE_FONT_SIZE, False)
                  for lines in visible_labels for line in lines)
    label_extent = max((len(lines) * 13 + 2 * LABEL_PADDING if direction == 'TB'
                        else max(text_width(line, EDGE_FONT_SIZE) for line in lines)
                        + 2 * LABEL_PADDING for lines in visible_labels), default=0)
    # Present reachable states in entry order so cycle breaking follows the
    # startup flow, rather than whichever state was declared first in the DSL.
    adjacency = {name: [] for name in nodes}
    for transition in transitions:
        adjacency[transition.source].append(transition.target)
    pending = deque(node.id for node in nodes.values() if node.kind == 'initial')
    ordered = {}
    while pending:
        name = pending.popleft()
        if name not in ordered:
            ordered[name] = nodes[name]
            pending.extend(adjacency[name])
    ordered.update(nodes)
    lines = ['digraph fsm {', f'  rankdir={direction};',
             f'  splines=ortho; nodesep=0.8; ranksep={(spacing + label_extent) / 72:.6f};',
             '  node [shape=box, fixedsize=true, label=""];',
             f'  edge [fontname="{EDGE_FONT_FAMILY}", fontsize={EDGE_FONT_SIZE}, arrowsize=0.8];']
    for node in ordered.values():
        shape = 'ellipse' if node.kind in ('initial', 'final') else 'diamond' if node.kind == 'choice' else 'box'
        lines.append(f'  {json.dumps(node.id)} [width={node.width / 72:.6f}, '
                     f'height={node.height / 72:.6f}, shape={shape}];')
    starts = [json.dumps(node.id) for node in nodes.values() if node.kind == 'initial']
    if starts:
        # A cycle may otherwise determine the first rank before dot encounters
        # the initial edge. "source" reserves that rank exclusively for start.
        lines.append('  { rank=source; ' + '; '.join(starts) + '; }')
    for index, (transition, label) in enumerate(zip(transitions, labels)):
        lines.append(f'  {json.dumps(transition.source)} -> {json.dumps(transition.target)} '
                     f'[id="edge_{index}", xlabel={dot_label(label)}];')
    lines.append('}')
    graph = run_graphviz('\n'.join(lines))
    left, bottom, right, top = (float(v) for v in graph['bb'].split(','))

    def point(value):
        x, y = (float(v) for v in value.split(','))
        return round(x - left, 3), round(top - y, 3)

    for obj in graph.get('objects', []):
        if obj['name'] not in nodes or 'pos' not in obj:
            continue  # Graphviz also emits the anonymous rank subgraph here.
        node = nodes[obj['name']]
        cx, cy = point(obj['pos'])
        node.x = round(cx - node.width / 2, 3)
        node.y = round(cy - node.height / 2, 3)

    routes = [None] * len(transitions)
    for edge in graph.get('edges', []):
        index = int(edge['id'].removeprefix('edge_'))
        start = end = None
        points = []
        for token in edge['pos'].split():
            if token.startswith('e,'):
                end = point(token[2:])
            elif token.startswith('s,'):
                start = point(token[2:])
            else:
                points.append(point(token))
        if start is not None:
            points.insert(0, start)
        if end is not None:
            points.append(end)
        points = simplify(points)
        if any(abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01
               for a, b in zip(points, points[1:])):
            raise DiagramError('Graphviz returned a non-orthogonal FSM transition route')
        routes[index] = EdgeRoute(points, point(edge['xlp']) if 'xlp' in edge else None)

    compact_initial_arrow(nodes, transitions, routes, labels)

    # Graphviz external captions sit beside their routes. Keep its choice of
    # nearby segment, but center the exported caption directly on that line.
    # Recompute visible bounds so trimming the initial arrow also removes the
    # space formerly occupied by its distant marker and Graphviz captions.
    xs = [x for n in nodes.values() for x in (n.x, n.x + n.width)]
    ys = [y for n in nodes.values() for y in (n.y, n.y + n.height)]
    xs.extend(x for route in routes for x, _ in route.points)
    ys.extend(y for route in routes for _, y in route.points)
    min_x, min_y = min(xs, default=0), min(ys, default=0)
    width, height = max(xs, default=0), max(ys, default=0)
    obstacles = [(n.x, n.y, n.x + n.width, n.y + n.height) for n in nodes.values()]
    positions = place_route_labels(routes, labels, obstacles)
    if positions is None:
        if _label_attempt < 3:
            return route_graph(nodes, transitions, labels, direction,
                               spacing * 1.5 + 24, _label_attempt + 1)
        raise DiagramError('Not enough room for FSM labels on their lines; increase transition-spacing')
    for index, anchor in positions.items():
        route, size = routes[index], label_size(labels[index])
        route.label = anchor
        x, y = route.label
        min_x, min_y = min(min_x, x - size[0] / 2), min(min_y, y - size[1] / 2)
        width, height = max(width, x + size[0] / 2), max(height, y + size[1] / 2)
    if min_x != 0 or min_y != 0:
        for node in nodes.values():
            node.x -= min_x
            node.y -= min_y
        for route in routes:
            route.points = [(x - min_x, y - min_y) for x, y in route.points]
            if route.label is not None:
                route.label = (route.label[0] - min_x, route.label[1] - min_y)
    return width - min_x, height - min_y, routes
