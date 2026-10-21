"""Check routing against actual boxes and exported draw.io coordinates."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

CLSGEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLSGEN))

from clsast import Parser, ClsError
from dotlayout import Rect
from layout import Layout
from routing import route_edges, Route, CLEARANCE, clear_borders, obstacles
from drawio_out import to_xml


def clear_segment(a, b, rect):
    """True if an orthogonal segment stays out of the rectangle's interior."""
    epsilon = 0.01
    if abs(a[0] - b[0]) < epsilon:
        return not (rect.x + epsilon < a[0] < rect.x + rect.width - epsilon
                    and max(a[1], b[1]) > rect.y + epsilon
                    and min(a[1], b[1]) < rect.y + rect.height - epsilon)
    if abs(a[1] - b[1]) < epsilon:
        return not (rect.y + epsilon < a[1] < rect.y + rect.height - epsilon
                    and max(a[0], b[0]) > rect.x + epsilon
                    and min(a[0], b[0]) < rect.x + rect.width - epsilon)
    return False


def exported_points(cells, edge):
    style = dict(p.split('=', 1) for p in edge.get('style').split(';') if '=' in p)

    def endpoint(name, prefix):
        cell = cells[name]
        g = cell.find('mxGeometry')
        x, y, w, h = (float(g.get(k)) for k in ('x', 'y', 'width', 'height'))
        parent = cells.get(cell.get('parent'))
        while parent is not None and parent.get('vertex') == '1':
            geometry = parent.find('mxGeometry')
            x += float(geometry.get('x'))
            y += float(geometry.get('y'))
            parent = cells.get(parent.get('parent'))
        return x + float(style[prefix + 'X']) * w, y + float(style[prefix + 'Y']) * h

    waypoints = [(float(p.get('x')), float(p.get('y')))
                 for p in edge.findall("mxGeometry/Array[@as='points']/mxPoint")]
    return [endpoint(edge.get('source'), 'exit'), *waypoints,
            endpoint(edge.get('target'), 'entry')]


class RoutingTest(unittest.TestCase):
    def test_internal_inheritance_stays_inside_its_component(self):
        cls = Parser().parse('package P {\ncomponent C {\ninterface I\nclass Combo\n'
                             'class Impl\n}\n}\nImpl ..|> I\nCombo ..> Impl\n')
        layout = Layout({'P': Rect(-24, -40, 448, 500), 'C': Rect(0, 0, 400, 420),
                         'I': Rect(24, 60, 160, 60), 'Combo': Rect(24, 160, 160, 60),
                         'Impl': Rect(24, 280, 160, 60)}, 450, 460)
        for route in route_edges(cls, layout).values():
            for x, y in route.points:
                self.assertTrue(8 <= x <= 392)
                self.assertTrue(34 <= y <= 412)
            for a, b in zip(route.points, route.points[1:]):
                self.assertTrue(clear_segment(a, b, layout.rects['Combo']))

    def test_border_clearance_moves_an_internal_detour_inward(self):
        cls = Parser().parse('component C {\ninterface I\nclass Impl\n}\nImpl ..|> I\n')
        layout = Layout({'C': Rect(0, 0, 240, 360), 'I': Rect(24, 60, 160, 60),
                         'Impl': Rect(24, 260, 160, 60)}, 260, 380)
        allowed = frozenset(('C',))
        original = Route((0, 0.5), (0, 0.5), [(24, 290), (0, 290), (0, 90), (24, 90)])
        route = clear_borders(original, cls.relations[0], cls, layout, allowed,
                              obstacles(cls, layout, allowed))
        self.assertEqual(route.points, [(24, 290), (8, 290), (8, 90), (24, 90)])
        self.assertEqual(route.source_port, (0, 0.5))
        self.assertEqual(route.target_port, (0, 0.5))

    def test_cross_component_connection_stays_inside_shared_package(self):
        cls = Parser().parse('package P {\ncomponent Left {\nclass A\n}\n'
                             'component Right {\nclass B\n}\n}\nA --> B\n')
        layout = Layout({'P': Rect(0, 0, 600, 400), 'Left': Rect(24, 60, 200, 250),
                         'A': Rect(48, 120, 160, 60), 'Right': Rect(360, 60, 200, 250),
                         'B': Rect(384, 120, 160, 60)}, 620, 420)
        route = route_edges(cls, layout)[0]
        for x, y in route.points:
            self.assertTrue(8 <= x <= 592)
            self.assertTrue(34 <= y <= 392)
        self.assertLess(route.points[0][0], 224)
        self.assertGreater(route.points[-1][0], 360)

    def test_clearance_does_not_make_close_container_obstacles_overlap(self):
        cls = Parser().parse('package App {\nclass A\nclass B\n}\n'
                             'package U {\nclass X\n}\npackage V {\nclass Y\n}\nA --> B\n')
        layout = Layout({'App': Rect(0, 0, 300, 300), 'A': Rect(40, 80, 100, 60),
                         'B': Rect(40, 200, 100, 60), 'U': Rect(400, 0, 160, 140),
                         'X': Rect(420, 60, 120, 60), 'V': Rect(400, 148, 160, 140),
                         'Y': Rect(420, 208, 120, 60)}, 600, 340)
        boxes = obstacles(cls, layout, frozenset(('App',)))
        self.assertLess(boxes['U'].x, layout.rects['U'].x)
        self.assertLess(boxes['U'].y + boxes['U'].height, boxes['V'].y)
        for route in route_edges(cls, layout).values():
            for a, b in zip(route.points, route.points[1:]):
                self.assertTrue(clear_segment(a, b, boxes['U']))
                self.assertTrue(clear_segment(a, b, boxes['V']))

    def test_graphviz_spline_fallback_is_reported_instead_of_exported(self):
        cls = Parser().parse('class A\nclass B\nA --> B\n')
        layout = Layout({'A': Rect(0, 0, 100, 60), 'B': Rect(200, 100, 100, 60)}, 340, 200)
        graph = {'edges': [{'id': 'route_0', '_draw_': [
            {'op': 'b', 'points': [(100, 170), (140, 150), (160, 90), (200, 70)]}]}]}
        with patch('routing.run_graphviz', return_value=graph):
            with self.assertRaisesRegex(ClsError, 'did not return an orthogonal route'):
                route_edges(cls, layout)

    def test_unrelated_container_is_solid_but_endpoint_container_is_accessible(self):
        cls = Parser().parse('package A {\nclass Source\n}\n'
                             'package Utilities {\ncomponent Utils\n}\n'
                             'package Middleware {\ncomponent Diagnostic\n}\n'
                             'Source ..> Diagnostic\nSource ..> Utils\n')
        layout = Layout({'A': Rect(0, 0, 300, 200), 'Source': Rect(200, 80, 80, 60),
                         'Utilities': Rect(430, 180, 180, 180), 'Utils': Rect(460, 240, 120, 60),
                         'Middleware': Rect(400, 400, 260, 160), 'Diagnostic': Rect(460, 460, 160, 60)},
                        700, 600)
        routes = route_edges(cls, layout)
        # The direct route would cross Utilities; its full area needs clearance.
        box = layout.rects['Utilities']
        obstacle = Rect(box.x - CLEARANCE, box.y - CLEARANCE,
                        box.width + 2 * CLEARANCE, box.height + 2 * CLEARANCE)
        for a, b in zip(routes[0].points, routes[0].points[1:]):
            self.assertTrue(clear_segment(a, b, obstacle), (a, b))
        x, y = routes[1].points[-1]
        self.assertTrue(box.x < x < box.x + box.width)
        self.assertTrue(box.y < y < box.y + box.height)

    def test_border_offset_chooses_side_without_colliding_with_child(self):
        cls = Parser().parse('component C {\nclass Source\nclass Blocker\n}\n'
                             'package Q {\nclass Target\n}\nSource ..> Target\n')
        layout = Layout({'C': Rect(0, 0, 220, 200), 'Source': Rect(100, 40, 100, 60),
                         'Blocker': Rect(180, 160, 36, 40), 'Q': Rect(140, 220, 180, 140),
                         'Target': Rect(180, 280, 100, 60)}, 340, 400)
        allowed = frozenset(('C', 'Q'))
        original = Route((1, 0.5), (0.4, 0), [(200, 70), (220, 70), (220, 280)])
        route = clear_borders(original, cls.relations[0], cls, layout, allowed,
                              obstacles(cls, layout, allowed))
        self.assertGreaterEqual(route.points[1][0], 220 + CLEARANCE)
        for a, b in zip(route.points, route.points[1:]):
            self.assertTrue(clear_segment(a, b, layout.rects['Blocker']))
        self.assertEqual(route.points[0], original.points[0])
        self.assertEqual(route.points[-1][1], 280)

    def test_dependency_avoids_intervening_interface_in_exported_diagram(self):
        cls = Parser().parse('class Settings\ninterface Flash\nclass FlashObject\n'
                             'Settings ..> FlashObject\nFlashObject ..|> Flash\n')
        layout = Layout({'Settings': Rect(0, 100, 120, 60),
                         'Flash': Rect(180, 100, 160, 60),
                         'FlashObject': Rect(180, 240, 160, 60)}, 400, 340)
        before = {name: vars(r).copy() for name, r in layout.rects.items()}
        xml = to_xml(cls, layout)
        cells = {c.get('id'): c for c in xml.iter('mxCell')}
        edge = cells['cls_edge_0']
        self.assertIn('noEdgeStyle=1;', edge.get('style'))
        points = exported_points(cells, edge)
        blocker = cells['cls_Flash'].find('mxGeometry')
        obstacle = Rect(*(float(blocker.get(k)) for k in ('x', 'y', 'width', 'height')))
        self.assertGreater(len(points), 2)
        for a, b in zip(points, points[1:]):
            self.assertTrue(clear_segment(a, b, obstacle), (a, b))
        self.assertEqual(before, {name: vars(r) for name, r in layout.rects.items()})
        self.assertEqual(ET.tostring(xml), ET.tostring(to_xml(cls, layout)))

    def test_multiple_obstacles_and_parallel_edges(self):
        cls = Parser().parse('class A\nclass B\nclass C\nclass D\n'
                             'A --> D\nA ..> D\n')
        layout = Layout({'A': Rect(0, 100, 100, 60), 'B': Rect(140, 50, 100, 160),
                         'C': Rect(280, 100, 100, 160), 'D': Rect(420, 100, 100, 60)},
                        550, 300)
        routes = route_edges(cls, layout)
        self.assertEqual(set(routes), {0, 1})
        for route in routes.values():
            for a, b in zip(route.points, route.points[1:]):
                for name in ('B', 'C'):
                    self.assertTrue(clear_segment(a, b, layout.rects[name]), (a, b, name))

    def test_explicit_horizontal_alignment_keeps_facing_ports_and_straight_line(self):
        cls = Parser().parse('arrange: LR\nalign-horizontal: A B\n'
                             'package P {\nclass A\n}\npackage Q {\nclass B\n}\nB ..> A\n')
        layout = Layout({'P': Rect(0, 0, 180, 180), 'A': Rect(30, 80, 120, 60),
                         'Q': Rect(300, 0, 180, 180), 'B': Rect(330, 80, 120, 60)},
                        500, 200)
        route = route_edges(cls, layout)[0]
        self.assertEqual(route.source_port, (0, 0.5))
        self.assertEqual(route.target_port, (1, 0.5))
        self.assertEqual(len(route.points), 2)

    def test_self_loop_fits_inside_exported_frame(self):
        cls = Parser().parse('class A\nA --> A\n')
        layout = Layout({'A': Rect(0, 0, 160, 60)}, 160, 60)
        xml = to_xml(cls, layout)
        cells = {c.get('id'): c for c in xml.iter('mxCell')}
        points = exported_points(cells, cells['cls_edge_0'])
        self.assertGreater(len(points), 3)
        frame = cells['cls_frame'].find('mxGeometry')
        for x, y in points:
            self.assertTrue(0 <= x <= float(frame.get('width')))
            self.assertTrue(0 <= y <= float(frame.get('height')))

    def test_no_edges_does_not_start_another_graphviz_process(self):
        cls = Parser().parse('class A\n')
        with patch('routing.run_graphviz') as graphviz:
            self.assertEqual(route_edges(cls, Layout({'A': Rect(0, 0, 160, 60)}, 160, 60)), {})
            graphviz.assert_not_called()

    def test_missing_neato_leaves_existing_output_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'dot').symlink_to(shutil.which('dot'))
            source, output = tmp / 'input.cls', tmp / 'output.drawio'
            source.write_text('class A\nclass B\nA --> B\n')
            output.write_text('existing diagram')
            result = subprocess.run([sys.executable, str(CLSGEN / 'main.py'), str(source),
                                     '-o', str(output)], env={**os.environ, 'PATH': str(tmp)},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Graphviz "neato" was not found', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(output.read_text(), 'existing diagram')


if __name__ == '__main__':
    unittest.main()
