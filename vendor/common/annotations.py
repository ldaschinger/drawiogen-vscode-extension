"""Shared anchored notes for class and state diagrams.

Callouts live in a column beside the existing diagram. Fixed orthogonal routes
avoid unrelated boxes, so adding notes does not move existing nodes or edges.
"""
from dataclasses import dataclass
from heapq import heappop, heappush
import xml.etree.ElementTree as ET

from diagramerror import DiagramError
from dotlayout import run_graphviz
import xmlout


@dataclass
class Note:
    target: str
    text: str
    line_number: int
    width: int = 240


def note_statement(items):
    return {'kind': 'note', 'target': str(items[0]), 'text': str(items[-1]),
            'width': int(items[1]) if len(items) == 3 else 240}


def make_note(node):
    if not node['text'].strip():
        raise DiagramError('Note text cannot be empty', node['line'])
    if not 80 <= node['width'] <= 1000:
        raise DiagramError('Note width must be between 80 and 1000', node['line'])
    return Note(node['target'], node['text'], node['line'], node['width'])


def note_lines(notes):
    """Measure glyphs once per diagram so narrow notes cannot clip wide text."""
    characters = sorted({char for note in notes for char in note.text.replace('\\n', '\n')
                         if not char.isspace()} | {' '})
    source = ['digraph metrics { node [shape=plain, fontname="Arial", fontsize=12];']
    for index, char in enumerate(characters):
        label = '&#160;' if char == ' ' else xmlout.escape(char)
        source.append(f'n{index} [label=<{label}>];')
    source.append('}')
    graph = run_graphviz('\n'.join(source))
    widths = {characters[int(obj['name'][1:])]: float(obj['width']) * 72
              for obj in graph.get('objects', [])}
    result = []
    for note in notes:
        available = note.width - 32
        lines = []
        for part in note.text.replace('\\n', '\n').split('\n'):
            current = ''
            for word in part.split():
                candidate = current + (' ' if current else '') + word
                if sum(widths[c] for c in candidate) <= available:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                    current = ''
                for char in word:
                    if current and sum(widths[c] for c in current + char) > available:
                        lines.append(current)
                        current = ''
                    current += char
            lines.append(current)
        result.append(lines)
    return result


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    def padded(self, padding=8):
        return Box(self.x - padding, self.y - padding,
                   self.width + 2 * padding, self.height + 2 * padding)


def intersects(a, b, box):
    eps = 0.001
    if a[0] == b[0]:
        return (box.x + eps < a[0] < box.right - eps
                and max(a[1], b[1]) > box.y + eps and min(a[1], b[1]) < box.bottom - eps)
    return (box.y + eps < a[1] < box.bottom - eps
            and max(a[0], b[0]) > box.x + eps and min(a[0], b[0]) < box.right - eps)


def route(start, end, obstacles):
    """A* on rectangle-side coordinates; only horizontal/vertical segments."""
    xs = sorted({start[0], end[0], *[x for b in obstacles for x in (b.x, b.right)]})
    ys = sorted({start[1], end[1], *[y for b in obstacles for y in (b.y, b.bottom)]})
    source = (xs.index(start[0]), ys.index(start[1]))
    target = (xs.index(end[0]), ys.index(end[1]))
    pending = [(0, 0, source)]
    costs, previous = {source: 0}, {}
    while pending:
        _, cost, node = heappop(pending)
        if cost != costs[node]:
            continue
        if node == target:
            result = [end]
            while node != source:
                node = previous[node]
                result.append((xs[node[0]], ys[node[1]]))
            result.reverse()
            simplified = []
            for point in result:
                while len(simplified) >= 2:
                    a, b = simplified[-2:]
                    if a[0] == b[0] == point[0] or a[1] == b[1] == point[1]:
                        simplified.pop()
                    else:
                        break
                simplified.append(point)
            return simplified
        x, y = node
        a = (xs[x], ys[y])
        for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            nx, ny = neighbor
            if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                continue
            b = (xs[nx], ys[ny])
            distance = abs(a[0]-b[0]) + abs(a[1]-b[1])
            next_cost = cost + distance
            if next_cost >= costs.get(neighbor, float('inf')):
                continue
            if any(intersects(a, b, obstacle) for obstacle in obstacles):
                continue
            costs[neighbor] = next_cost
            previous[neighbor] = node
            heuristic = abs(b[0]-end[0]) + abs(b[1]-end[1])
            heappush(pending, (next_cost + heuristic, next_cost, neighbor))
    return None


def add_notes(root, notes, cell_id, frame_id):
    if not notes:
        return
    cells = {c.get('id'): c for c in root.findall('mxCell')}
    frame = cells[frame_id].find('mxGeometry')
    column = float(frame.get('width')) + 42
    boxes = {}

    def absolute(name):
        if name in boxes:
            return boxes[name]
        cell = cells[name]
        g = cell.find('mxGeometry')
        x, y = float(g.get('x', 0)), float(g.get('y', 0))
        parent = cell.get('parent')
        if parent not in ('0', '1'):
            p = absolute(parent)
            x, y = x + p.x, y + p.y
        boxes[name] = Box(x, y, float(g.get('width')), float(g.get('height')))
        return boxes[name]

    # Member rows and component icons are covered by their parent box.
    vertices = {name: c for name, c in cells.items()
                if c.get('vertex') == '1' and name != frame_id
                and c.find('mxGeometry').get('relative') != '1'}
    children = {}
    for name, cell in vertices.items():
        children.setdefault(cell.get('parent'), []).append(name)
    next_y = 60
    placed = []
    for index, (note, lines) in enumerate(zip(notes, note_lines(notes))):
        target_id = cell_id(note.target)
        target = absolute(target_id)
        height = max(56, 24 + len(lines) * 16)
        box = Box(column, max(next_y, target.y + target.height / 2 - height / 2), note.width, height)
        ancestors = set()
        parent = cells[target_id].get('parent')
        while parent not in ('0', '1'):
            ancestors.add(parent)
            parent = cells[parent].get('parent')
        obstacles = [box] + [b.padded() for b in placed]

        def visit(name):
            rect = absolute(name)
            if name in ancestors:
                # Leave an ancestor's body traversable, while avoiding its title.
                obstacles.append(Box(rect.x, rect.y, rect.width, min(30, rect.height)).padded())
                for child in children.get(name, []):
                    visit(child)
            else:
                obstacles.append(rect.padded())

        for name in children.get('1', []):
            visit(name)
        end = (box.x, box.y + box.height / 2)
        ports = [((target.right, target.y + target.height / 2), (12, 0)),
                 ((target.x + target.width / 2, target.bottom), (0, 12)),
                 ((target.x + target.width / 2, target.y), (0, -12)),
                 ((target.x, target.y + target.height / 2), (-12, 0))]
        points = None
        for start, offset in ports:
            outside = (start[0] + offset[0], start[1] + offset[1])
            other_obstacles = [b for b in obstacles if b != target.padded()]
            if any(intersects(start, outside, b) for b in other_obstacles):
                continue
            routed = route(outside, end, obstacles)
            if routed:
                points = [start] + routed
                break
        if points is None:
            raise DiagramError(f'Not enough room to connect note on "{note.target}"', note.line_number)
        note_id = cell_id(f'$note_{index}')
        value = '<br>'.join(xmlout.escape(line) for line in lines)
        xmlout.add_vertex(root, note_id, value,
                          'shape=note;size=16;whiteSpace=wrap;html=1;align=left;verticalAlign=top;'
                          'spacing=10;fillColor=#fff2cc;strokeColor=#666666;fontSize=12;fontFamily=Arial;',
                          box.x, box.y, box.width, box.height)
        start = points[0]
        style = ('noEdgeStyle=1;rounded=0;dashed=1;html=1;endArrow=none;startArrow=none;'
                 f'exitX={(start[0]-target.x)/target.width};exitY={(start[1]-target.y)/target.height};'
                 'exitPerimeter=0;entryX=0;entryY=0.5;entryPerimeter=0;strokeColor=#666666;')
        edge_id = cell_id(f'$note_link_{index}')
        xmlout.add_edge(root, edge_id, target_id, note_id, '', style)
        geometry = root.find(f"mxCell[@id='{edge_id}']/mxGeometry")
        array = ET.SubElement(geometry, 'Array', attrib={'as': 'points'})
        for x, y in points[1:-1]:
            ET.SubElement(array, 'mxPoint', attrib={'x': str(x), 'y': str(y)})
        frame.set('width', str(max(float(frame.get('width')), box.right + 30,
                                   max(x for x, _ in points) + 30)))
        frame.set('height', str(max(float(frame.get('height')), box.bottom + 30,
                                    max(y for _, y in points) + 30)))
        placed.append(box)
        next_y = box.bottom + 24
