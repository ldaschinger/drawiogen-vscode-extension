import os
import sys
import math
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

import xmlout
from annotations import add_notes
from xmlout import escape

from fsmast import Fsm
from layout import Layout, state_lines, display_state_lines, split_text, wrap_edge_label
from fsmrouting import midpoint, EDGE_FONT_FAMILY, EDGE_FONT_SIZE
from textmetrics import FONT_FAMILY, measure_texts, text_width

STATE_STYLE = ('rounded=1;arcSize=12;whiteSpace=wrap;html=1;align=left;verticalAlign=top;'
               'spacingLeft=8;spacingRight=8;spacingTop=4;fillColor=#ffffff;strokeColor=#000000;'
               f'fontFamily={FONT_FAMILY};')
CHOICE_STYLE = ('rhombus;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;'
                'verticalLabelPosition=bottom;verticalAlign=top;labelPosition=right;align=left;')
INITIAL_STYLE = 'ellipse;html=1;fillColor=#000000;strokeColor=#000000;'
FINAL_STYLE = 'ellipse;html=1;shape=endState;fillColor=#000000;strokeColor=#000000;'
EDGE_STYLE = ('edgeStyle=none;noEdgeStyle=1;rounded=0;orthogonalLoop=0;html=1;'
              'endArrow=open;endFill=0;endSize=8;labelBackgroundColor=#ffffff;'
              f'fontFamily={EDGE_FONT_FAMILY};fontSize={EDGE_FONT_SIZE};')
FRAME_FONT_SIZE = 12
FRAME_TITLE_PADDING = 32  # left/right spacing and the slanted tab corner


def html_text(text: str) -> str:
    return '<br>'.join(escape(part) for part in split_text(text))


def html_body_line(text: str) -> str:
    """Escapes one body line and keeps its leading indentation visible."""
    stripped = text.lstrip(' ')
    return '&nbsp;' * (len(text) - len(stripped)) + escape(stripped)


def state_value(state) -> str:
    value = f'<div style="text-align:center"><b><font style="font-size:12px">{html_text(state.label)}</font></b></div>'
    lines = display_state_lines(state)
    if lines:
        body = '<br>'.join(html_body_line(line) for line in lines)
        value += f'<hr size="1" style="margin:4px 0"><font style="font-size:10px">{body}</font>'
    return value


def cell_id(name: str) -> str:
    return 'fsm_' + name


def title_tab_width(title: str) -> int:
    """Measure using the same font as the viewer instead of a fixed-width tab."""
    if not title:
        return 160
    measure_texts([(title, FRAME_FONT_SIZE, False)])
    width = text_width(title, FRAME_FONT_SIZE)
    return max(160, math.ceil(width) + FRAME_TITLE_PADDING)


def port_style(node, point, prefix):
    x = (point[0] - node.x) / node.width
    y = (point[1] - node.y) / node.height
    return (f'{prefix}X={x:.6f};{prefix}Y={y:.6f};'
            f'{prefix}Dx=0;{prefix}Dy=0;{prefix}Perimeter=0;')


def add_routed_edge(root, index, transition, route, layout, dx, dy):
    label = '<br>'.join(escape(line) for line in layout.edge_labels[index])
    style = EDGE_STYLE + port_style(layout.nodes[transition.source], route.points[0], 'exit')
    style += port_style(layout.nodes[transition.target], route.points[-1], 'entry')
    cell = ET.SubElement(root, 'mxCell', attrib={
        'id': f'fsm_edge_{index}', 'value': label, 'style': style, 'parent': '1', 'edge': '1',
        'source': cell_id(transition.source), 'target': cell_id(transition.target)})
    geometry = ET.SubElement(cell, 'mxGeometry', attrib={'relative': '1', 'as': 'geometry'})
    if route.points[1:-1]:
        points = ET.SubElement(geometry, 'Array', attrib={'as': 'points'})
        for x, y in route.points[1:-1]:
            ET.SubElement(points, 'mxPoint', attrib={'x': str(x + dx), 'y': str(y + dy)})
    if route.label is not None:
        mid = midpoint(route.points)
        ET.SubElement(geometry, 'mxPoint', attrib={
            'as': 'offset', 'x': str(round(route.label[0] - mid[0], 3)),
            'y': str(round(route.label[1] - mid[1], 3))})


def to_xml(fsm: Fsm, layout: Layout) -> ET.Element:
    mxfile, root = xmlout.new_document('fsmgen', fsm.title or 'FSM')
    dx, dy = xmlout.add_frame(root, 'fsm_frame', fsm.title, layout.width, layout.height,
                             title_width=title_tab_width(fsm.title))
    frame = root.find("mxCell[@id='fsm_frame']")
    frame.set('style', frame.get('style').replace('whiteSpace=wrap;', 'whiteSpace=nowrap;')
              + f'fontFamily={EDGE_FONT_FAMILY};fontSize={FRAME_FONT_SIZE};')

    for node in layout.nodes.values():
        x, y = node.x + dx, node.y + dy
        if node.kind == 'state':
            state = fsm.states[node.id]
            style = STATE_STYLE if state_lines(state) else STATE_STYLE.replace('align=left;verticalAlign=top;', 'align=center;verticalAlign=middle;')
            xmlout.add_vertex(root, cell_id(node.id), state_value(state), style,
                              x, y, node.width, node.height)
        elif node.kind == 'choice':
            xmlout.add_vertex(root, cell_id(node.id), escape(fsm.choices[node.id].label), CHOICE_STYLE,
                              x, y, node.width, node.height)
        elif node.kind == 'initial':
            xmlout.add_vertex(root, cell_id(node.id), '', INITIAL_STYLE, x, y, node.width, node.height)
        else:
            xmlout.add_vertex(root, cell_id(node.id), '', FINAL_STYLE, x, y, node.width, node.height)

    for index, t in enumerate(fsm.transitions):
        add_routed_edge(root, index, t, layout.routes[index], layout, dx, dy)

    add_notes(root, fsm.notes, cell_id, 'fsm_frame')
    return mxfile


xml_pretty = xmlout.xml_pretty
