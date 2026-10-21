"""Keep the edge geometry and label placement from the FSM's Graphviz layout.

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

Point = Tuple[float, float]
EDGE_FONT_SIZE = 11
EDGE_FONT_FAMILY = 'Arial'
LABEL_PADDING = 8


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
    """Remove repeated/collinear Bezier control points from dot's polyline output."""
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


def route_graph(nodes, transitions, labels, direction, spacing=50.4):
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
             f'  splines=polyline; nodesep=0.8; ranksep={spacing / 72:.6f};',
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
                     f'[id="edge_{index}", label={dot_label(label)}];')
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
        routes[index] = EdgeRoute(simplify(points), point(edge['lp']) if 'lp' in edge else None)
    return right - left, top - bottom, routes
