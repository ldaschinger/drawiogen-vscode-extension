"""Graph layout through Graphviz `dot`. Supports nested containers (dot clusters)."""
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from diagramerror import DiagramError

CLUSTER_MARGIN = 24
CLUSTER_LABEL_LINES = 2     # reserves room for the container title at the top


@dataclass
class GNode:
    id: str
    width: float = 0
    height: float = 0
    label: str = ''                              # container title
    children: List['GNode'] = field(default_factory=list)
    is_container: bool = False
    top_row: List[str] = field(default_factory=list)


@dataclass
class GEdge:
    source: str
    target: str
    label_lines: List[str] = field(default_factory=list)


@dataclass
class Rect:
    x: float
    y: float
    width: float
    height: float


def _quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', "'") + '"'


def _emit_node(node: GNode, out: List[str], indent: str) -> None:
    if node.is_container:
        out.append(f'{indent}subgraph {_quote("cluster_" + node.id)} {{')
        title = node.label.replace('"', "'") + '\\n' * (CLUSTER_LABEL_LINES - 1) + ' '
        out.append(f'{indent}  label="{title}"; labeljust=l; labelloc=t;')
        out.append(f'{indent}  margin={CLUSTER_MARGIN}; fontsize=12;')
        for child in node.children:
            _emit_node(child, out, indent + '  ')
        if node.top_row:
            out.append(indent + '  { rank=min; ' + '; '.join(_quote(n) for n in node.top_row) + '; }')
        out.append(f'{indent}}}')
    else:
        out.append(f'{indent}{_quote(node.id)} '
                   f'[width={node.width / 72:.4f}, height={node.height / 72:.4f}];')


def dot_source(roots: List[GNode], edges: List[GEdge], direction: str,
               nodesep: float, ranksep: float) -> str:
    out = ['digraph g {',
           f'  rankdir={direction};',
           f'  nodesep={nodesep}; ranksep={ranksep};',
           '  node [shape=box, fixedsize=true, fontsize=10];',
           '  edge [fontsize=10];']

    for root in roots:
        _emit_node(root, out, '  ')

    for edge in edges:
        label = '\\n'.join(line.replace('"', "'") for line in edge.label_lines)
        out.append(f'  {_quote(edge.source)} -> {_quote(edge.target)} [label="{label}"];')

    out.append('}')
    return '\n'.join(out) + '\n'


def run_graphviz(source: str, engine: str = 'dot', args: Tuple[str, ...] = ()) -> dict:
    if shutil.which(engine) is None:
        raise DiagramError(f'Graphviz "{engine}" was not found on PATH (install graphviz)')

    result = subprocess.run([engine, *args, '-Tjson'], input=source.encode('utf-8'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode != 0:
        raise DiagramError('Graphviz failed: ' + result.stderr.decode('utf-8', 'replace').strip())

    return json.loads(result.stdout)


def run_dot(source: str) -> dict:
    return run_graphviz(source)


def layout_graph(roots: List[GNode], edges: List[GEdge], direction: str = 'TB',
                 nodesep: float = 0.7, ranksep: float = 1.0) -> Tuple[Dict[str, Rect], int, int]:
    """Returns absolute top-left rectangles for every node and container, plus the total size."""
    graph = run_dot(dot_source(roots, edges, direction, nodesep, ranksep))

    bb = [float(v) for v in graph['bb'].split(',')]
    total_w, total_h = bb[2] - bb[0], bb[3] - bb[1]

    sizes: Dict[str, GNode] = {}

    def collect(node: GNode) -> None:
        sizes[node.id] = node
        for child in node.children:
            collect(child)

    for root in roots:
        collect(root)

    rects: Dict[str, Rect] = {}
    for obj in graph.get('objects', []):
        name = obj['name']
        if name.startswith('cluster_') and name[len('cluster_'):] in sizes and 'bb' in obj:
            llx, lly, urx, ury = (float(v) for v in obj['bb'].split(','))
            rects[name[len('cluster_'):]] = Rect(round(llx), round(total_h - ury),
                                                 round(urx - llx), round(ury - lly))
        elif name in sizes and 'pos' in obj:
            node = sizes[name]
            cx, cy = (float(v) for v in obj['pos'].split(','))
            rects[name] = Rect(round(cx - node.width / 2), round(total_h - cy - node.height / 2),
                               node.width, node.height)

    return rects, round(total_w), round(total_h)
