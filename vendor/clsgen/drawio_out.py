import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

import xmlout
from annotations import add_notes
from xmlout import escape

from clsast import Cls, Element
from layout import (Layout, attribute_rows, method_rows, header_height,
                    ROW_HEIGHT, DIVIDER_HEIGHT, CHAR_WIDTH, PACKAGE_TAB_HEIGHT)
from routing import route_edges

COMPONENT_STYLE = ('swimlane;fontStyle=1;align=center;verticalAlign=top;startSize={start};html=1;'
                   'whiteSpace=wrap;spacingLeft=30;spacingRight=30;collapsible=0;'
                   'fillColor=#ffffff;strokeColor=#000000;')
# PS component containers have a title and corner icon without a header divider.
COMPONENT_CONTAINER_STYLE = ('rounded=0;fontStyle=1;align=center;verticalAlign=top;html=1;'
                             'whiteSpace=wrap;spacingLeft=30;spacingRight=30;spacingTop=4;'
                             'container=1;collapsible=0;recursiveResize=0;'
                             'fillColor=#ffffff;strokeColor=#000000;')
COMPONENT_ICON_STYLE = 'shape=module;jettyWidth=8;jettyHeight=4;html=1;fillColor=#ffffff;strokeColor=#000000;'
COMPONENT_ICON_SIZE = (20, 20)
COMPONENT_ICON_OFFSET = (-27, 3)
# The package name is drawn by the folder shape itself, inside its tab (top-left).
PACKAGE_STYLE = ('shape=folder;tabWidth={tab_width};tabHeight={tab_height};tabPosition=left;fontStyle=1;'
                 'align=left;spacingLeft=8;spacingTop=3;verticalAlign=top;html=1;whiteSpace=wrap;'
                 'container=1;collapsible=0;recursiveResize=0;fillColor=#ffffff;strokeColor=#000000;')
PACKAGE_TAB_MIN_WIDTH = 70
PACKAGE_TAB_CHAR_WIDTH = 7.6
PACKAGE_TAB_PADDING = 24
CLASS_STYLE = ('swimlane;fontStyle=1;align=center;verticalAlign=top;childLayout=stackLayout;'
               'horizontal=1;startSize={start};horizontalStack=0;resizeParent=1;resizeParentMax=0;'
               'resizeLast=0;collapsible=0;marginBottom=0;html=1;whiteSpace=wrap;'
               'fillColor=#ffffff;strokeColor=#000000;')
MEMBER_STYLE = ('text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;spacingLeft=4;'
                'spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];'
                'portConstraint=eastwest;html=1;whiteSpace=wrap;')
DIVIDER_STYLE = ('line;strokeWidth=1;fillColor=none;align=left;verticalAlign=middle;spacingTop=-1;'
                 'spacingLeft=3;spacingRight=3;rotatable=0;labelPosition=right;points=[];'
                 'portConstraint=eastwest;strokeColor=inherit;')
# Preserve explicit orthogonal paths instead of asking draw.io to reroute them.
EDGE_BASE = ('noEdgeStyle=1;rounded=0;html=1;'
             'labelBackgroundColor=#ffffff;')
EDGE_ARROWS = {
    '--|>': 'endArrow=block;endFill=0;endSize=12;',
    '..|>': 'dashed=1;endArrow=block;endFill=0;endSize=12;',
    '*--': 'startArrow=diamondThin;startFill=1;startSize=14;endArrow=none;',
    'o--': 'startArrow=diamondThin;startFill=0;startSize=14;endArrow=none;',
    '-->': 'endArrow=open;endFill=0;',
    '..>': 'dashed=1;endArrow=open;endFill=0;',
    '--': 'endArrow=none;',
    '..': 'dashed=1;endArrow=none;',
}


ICON_SUFFIX = '_icon'


def cell_id(name: str) -> str:
    return 'cls_' + name


def header_value(element: Element) -> str:
    name = f'<b>{escape(element.label)}</b>'
    if element.stereotype:
        return f'<span style="font-weight:normal">«{escape(element.stereotype)}»</span><br>{name}'
    return name


def package_style(element: Element) -> str:
    tab_width = max(PACKAGE_TAB_MIN_WIDTH,
                    round(len(element.label) * PACKAGE_TAB_CHAR_WIDTH + PACKAGE_TAB_PADDING))
    return PACKAGE_STYLE.format(tab_width=tab_width, tab_height=PACKAGE_TAB_HEIGHT)


def add_component(root, element: Element, rect, x, y, parent: str, container: bool) -> None:
    start = header_height(element)
    style = (COMPONENT_CONTAINER_STYLE if container else COMPONENT_STYLE).format(start=start)
    xmlout.add_vertex(root, cell_id(element.id), header_value(element), style,
                      x, y, rect.width, rect.height, parent)
    xmlout.add_corner_vertex(root, cell_id(element.id) + ICON_SUFFIX, COMPONENT_ICON_STYLE,
                             cell_id(element.id), *COMPONENT_ICON_SIZE, *COMPONENT_ICON_OFFSET)


def add_classifier(root, element: Element, rect, x, y, parent: str) -> None:
    start = header_height(element)
    xmlout.add_vertex(root, cell_id(element.id), header_value(element),
                      CLASS_STYLE.format(start=start), x, y, rect.width, rect.height, parent)

    # A header and one empty body compartment match the project's overview notation.
    if not element.members:
        return

    offset = start
    for member in attribute_rows(element):
        text = f'{member.visibility} {member.text}'.strip()
        xmlout.add_vertex(root, f'{cell_id(element.id)}_m{offset}', escape(text), MEMBER_STYLE,
                          0, offset, rect.width, ROW_HEIGHT, cell_id(element.id))
        offset += ROW_HEIGHT

    if element.kind == 'enum':
        return

    xmlout.add_vertex(root, f'{cell_id(element.id)}_div', '', DIVIDER_STYLE,
                      0, offset, rect.width, DIVIDER_HEIGHT, cell_id(element.id))
    offset += DIVIDER_HEIGHT

    for member in method_rows(element):
        text = f'{member.visibility} {member.text}'.strip()
        xmlout.add_vertex(root, f'{cell_id(element.id)}_m{offset}', escape(text), MEMBER_STYLE,
                          0, offset, rect.width, ROW_HEIGHT, cell_id(element.id))
        offset += ROW_HEIGHT


def add_element(root, cls: Cls, element: Element, layout: Layout, dx: int, dy: int) -> None:
    rect = layout.rects[element.id]

    if element.parent is None:
        x, y, parent = rect.x + dx, rect.y + dy, '1'
    else:
        parent_rect = layout.rects[element.parent]
        x, y, parent = rect.x - parent_rect.x, rect.y - parent_rect.y, cell_id(element.parent)

    if element.is_container:
        if element.kind == 'package':
            xmlout.add_vertex(root, cell_id(element.id), escape(element.label), package_style(element),
                              x, y, rect.width, rect.height, parent)
        else:
            add_component(root, element, rect, x, y, parent, container=True)
        for child in element.children:
            add_element(root, cls, child, layout, dx, dy)
    elif element.kind == 'component':
        add_component(root, element, rect, x, y, parent, container=False)
    else:
        add_classifier(root, element, rect, x, y, parent)


def to_xml(cls: Cls, layout: Layout) -> ET.Element:
    routes = route_edges(cls, layout)
    points = [p for route in routes.values() for p in route.points]
    left = min([0] + [x for x, _ in points])
    top = min([0] + [y for _, y in points])
    width = max([layout.width] + [x for x, _ in points]) - left
    height = max([layout.height] + [y for _, y in points]) - top
    mxfile, root = xmlout.new_document('clsgen', cls.title or 'Class diagram')
    title_width = max(160, round(len(cls.title) * CHAR_WIDTH + 30))
    dx, dy = xmlout.add_frame(root, 'cls_frame', cls.title, width, height,
                             title_width=title_width)
    dx, dy = dx - left, dy - top

    for element in cls.roots:
        add_element(root, cls, element, layout, dx, dy)

    for index, relation in enumerate(cls.relations):
        edge_id = f'cls_edge_{index}'
        route = routes[index]
        style = EDGE_BASE + EDGE_ARROWS[relation.arrow]
        style += (f'exitX={route.source_port[0]:.12g};exitY={route.source_port[1]:.12g};exitPerimeter=0;'
                  f'entryX={route.target_port[0]:.12g};entryY={route.target_port[1]:.12g};entryPerimeter=0;')
        xmlout.add_edge(root, edge_id, cell_id(relation.source), cell_id(relation.target),
                        escape(relation.label), style)
        if len(route.points) > 2:
            geometry = root.find(f"mxCell[@id='{edge_id}']/mxGeometry")
            waypoints = ET.SubElement(geometry, 'Array', attrib={'as': 'points'})
            for x, y in route.points[1:-1]:
                ET.SubElement(waypoints, 'mxPoint', attrib={'x': str(x + dx), 'y': str(y + dy)})
        if relation.src_mult:
            xmlout.add_edge_label(root, edge_id + '_src', edge_id, escape(relation.src_mult), -0.85)
        if relation.tgt_mult:
            xmlout.add_edge_label(root, edge_id + '_tgt', edge_id, escape(relation.tgt_mult), 0.85)

    add_notes(root, cls.notes, cell_id, 'cls_frame')
    return mxfile


xml_pretty = xmlout.xml_pretty
