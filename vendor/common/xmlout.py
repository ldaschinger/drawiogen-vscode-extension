"""Minimal draw.io (mxfile) writer with deterministic ids."""
import html
import xml.etree.ElementTree as ET
from typing import Tuple

FRAME_MARGIN = 30
FRAME_TITLE_HEIGHT = 30
FRAME_STYLE = 'shape=umlFrame;whiteSpace=wrap;html=1;pointerEvents=0;width=160;height=30;'


def escape(text: str) -> str:
    return html.escape(text)


def new_document(agent: str, title: str) -> Tuple[ET.Element, ET.Element]:
    mxfile = ET.Element('mxfile', attrib={'host': agent, 'agent': agent, 'version': '26.2.2'})
    diagram = ET.SubElement(mxfile, 'diagram', attrib={'name': title or agent, 'id': agent + '_page'})
    model = ET.SubElement(diagram, 'mxGraphModel', attrib={
        'dx': '0', 'dy': '0', 'grid': '1', 'gridSize': '10', 'guides': '1', 'tooltips': '1',
        'connect': '1', 'arrows': '1', 'fold': '1', 'page': '0', 'pageScale': '1',
        'pageWidth': '851', 'pageHeight': '1100', 'background': '#ffffff', 'math': '0', 'shadow': '0'})
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', attrib={'id': '0'})
    ET.SubElement(root, 'mxCell', attrib={'id': '1', 'parent': '0'})
    return mxfile, root


def add_frame(root: ET.Element, id_: str, title: str, content_w: float, content_h: float,
              title_width: int = 160) -> Tuple[int, int]:
    """Adds the UML frame around the content. Returns the offset to apply to top-level content."""
    dx = FRAME_MARGIN
    dy = FRAME_MARGIN + FRAME_TITLE_HEIGHT
    style = FRAME_STYLE.replace('width=160;', f'width={title_width};')
    add_vertex(root, id_, escape(title), style, 0, 0,
               max(content_w + 2 * FRAME_MARGIN, title_width + FRAME_MARGIN),
               content_h + dy + FRAME_MARGIN)
    return dx, dy


def add_vertex(root: ET.Element, id_: str, value: str, style: str, x, y, w, h,
               parent: str = '1') -> None:
    cell = ET.SubElement(root, 'mxCell', attrib={
        'id': id_, 'value': value, 'style': style, 'parent': parent, 'vertex': '1'})
    ET.SubElement(cell, 'mxGeometry', attrib={
        'x': str(x), 'y': str(y), 'width': str(w), 'height': str(h), 'as': 'geometry'})


def add_corner_vertex(root: ET.Element, id_: str, style: str, parent: str, w: float, h: float,
                      offset_x: float, offset_y: float) -> None:
    """Small vertex pinned to the top-right corner of its parent (e.g. a component icon)."""
    cell = ET.SubElement(root, 'mxCell', attrib={
        'id': id_, 'value': '', 'style': style, 'parent': parent, 'vertex': '1'})
    geometry = ET.SubElement(cell, 'mxGeometry', attrib={
        'x': '1', 'width': str(w), 'height': str(h), 'relative': '1', 'as': 'geometry'})
    ET.SubElement(geometry, 'mxPoint', attrib={'x': str(offset_x), 'y': str(offset_y), 'as': 'offset'})


def add_edge(root: ET.Element, id_: str, source: str, target: str, value: str, style: str) -> None:
    cell = ET.SubElement(root, 'mxCell', attrib={
        'id': id_, 'value': value, 'style': style, 'parent': '1', 'edge': '1',
        'source': source, 'target': target})
    ET.SubElement(cell, 'mxGeometry', attrib={'relative': '1', 'as': 'geometry'})


def add_edge_label(root: ET.Element, id_: str, edge_id: str, value: str, relative_x: float) -> None:
    """Label attached to one end of an edge (e.g. multiplicity). relative_x: -1 = source, 1 = target."""
    cell = ET.SubElement(root, 'mxCell', attrib={
        'id': id_, 'value': value, 'parent': edge_id, 'vertex': '1', 'connectable': '0',
        'style': 'edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];'})
    geometry = ET.SubElement(cell, 'mxGeometry', attrib={
        'x': str(relative_x), 'relative': '1', 'as': 'geometry'})
    ET.SubElement(geometry, 'mxPoint', attrib={'as': 'offset'})


def xml_pretty(element: ET.Element) -> str:
    xml_str = ET.tostring(element, encoding='utf-8', xml_declaration=False).decode('utf-8')
    output = ''
    indent = 0

    for line in xml_str.replace('>', '>\n').split('\n'):
        if not line:
            continue
        if line.startswith('</'):
            indent -= 2
        output += (' ' * indent) + line + '\n'
        if not line.startswith('</') and not line.endswith('/>'):
            indent += 2

    return output
