"""Regression cases for overlapping forward, return, parallel and loop arrows."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsmast import Parser
from layout import build_nodes, layout_fsm
from drawio_out import to_xml
from diagramerror import DiagramError
from fsmrouting import EdgeRoute, label_size, midpoint, place_route_labels, route_graph
from textmetrics import measure_texts


ALARM = '''state Disabled
state Signalling
state Pause
initial -> Disabled
Disabled -> Signalling : start /\\nstart signalling
Signalling -> Pause : alarming time elapsed /\\nstop signalling
Pause -> Disabled : stop /
Signalling -> Disabled : stop /\\nstop signalling
Pause -> Signalling : pause time elapsed /\\nstart signalling
'''

PARALLEL = '''state Idle
state Erase
state Write
state Error
initial -> Idle
Idle -> Erase : store request &&\\ncontent changed / erase flash page
Erase -> Write : operation success / write double word
Erase -> Idle : operation failed / notify client
Write -> Idle : operation failed / notify client
Write -> Idle : all bytes written / notify client
Write -> Write : operation success && bytes pending / write double word
Write -> Error : store request / assertion
Erase -> Error : store request / assertion
Error -> final
'''


def shared_length(a, b, c, d):
    length = math.dist(a, b)
    if not length:
        return 0
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    distances = [abs(ux * (p[1] - a[1]) - uy * (p[0] - a[0])) for p in (c, d)]
    if max(distances) > 0.5:
        return 0
    lo, hi = sorted((p[0] - a[0]) * ux + (p[1] - a[1]) * uy for p in (c, d))
    return max(0, min(length, hi) - max(0, lo))


class RoutingTest(unittest.TestCase):
    def assert_no_shared_segments(self, routes):
        for index, route in enumerate(routes):
            for other in routes[index + 1:]:
                for a, b in zip(route.points, route.points[1:]):
                    for c, d in zip(other.points, other.points[1:]):
                        self.assertLessEqual(shared_length(a, b, c, d), 4,
                                             'Different transitions share an arrow segment')

    def test_bidirectional_alarm_cycle_has_separate_routes(self):
        self.assert_no_shared_segments(layout_fsm(Parser().parse(ALARM)).routes)

    def test_parallel_transitions_and_self_loop_have_separate_routes(self):
        fsm = Parser().parse(PARALLEL)
        layout = layout_fsm(fsm)
        self.assert_no_shared_segments(layout.routes)
        parallel = [route for t, route in zip(fsm.transitions, layout.routes)
                    if t.source == 'Write' and t.target == 'Idle']
        self.assertNotEqual(parallel[0].points, parallel[1].points)
        self.assertNotEqual(parallel[0].label, parallel[1].label)
        loop = next(route for t, route in zip(fsm.transitions, layout.routes) if t.source == t.target)
        node = layout.nodes['Write']
        self.assertGreater(max(x for x, _ in loop.points), node.x + node.width)
        # The loop may use ports above and below the state. Its entire path,
        # rather than only its rightmost point, must avoid the state's interior.
        for a, b in zip(loop.points, loop.points[1:]):
            if abs(a[0] - b[0]) < 0.01:
                self.assertFalse(node.x < a[0] < node.x + node.width
                                 and max(a[1], b[1]) > node.y + 0.5
                                 and min(a[1], b[1]) < node.y + node.height - 0.5)
            else:
                self.assertFalse(node.y < a[1] < node.y + node.height
                                 and max(a[0], b[0]) > node.x + 0.5
                                 and min(a[0], b[0]) < node.x + node.width - 0.5)
        self.assertGreater(math.dist(loop.points[0], loop.points[-1]), 5)

    def test_export_pins_ports_waypoints_and_label_offsets(self):
        fsm = Parser().parse(PARALLEL)
        layout = layout_fsm(fsm)
        cells = {c.get('id'): c for c in to_xml(fsm, layout).iter('mxCell')}
        has_waypoints = has_offset = False
        for index, route in enumerate(layout.routes):
            cell = cells[f'fsm_edge_{index}']
            self.assertIn('noEdgeStyle=1;', cell.get('style'))
            self.assertIn('exitX=', cell.get('style'))
            self.assertIn('entryX=', cell.get('style'))
            geometry = cell.find('mxGeometry')
            if len(route.points) > 2:
                self.assertEqual(len(geometry.findall('Array/mxPoint')), len(route.points) - 2)
                has_waypoints = True
            if route.label is not None:
                self.assertIsNotNone(geometry.find("mxPoint[@as='offset']"))
                has_offset = True
        self.assertTrue(has_waypoints)
        self.assertTrue(has_offset)

    def test_left_to_right_layout_also_separates_return_arrows(self):
        fsm = Parser().parse('direction: LR\n' + ALARM)
        layout = layout_fsm(fsm)
        self.assertGreater(layout.nodes['Signalling'].x, layout.nodes['Disabled'].x)
        self.assert_no_shared_segments(layout.routes)

    def test_transitions_have_only_horizontal_and_vertical_segments(self):
        for direction in ('TB', 'LR'):
            for source in (ALARM, PARALLEL):
                with self.subTest(direction=direction, source=source):
                    fsm = Parser().parse(f'direction: {direction}\n' + source)
                    layout = layout_fsm(fsm)
                    self.assert_no_shared_segments(layout.routes)
                    for transition, route in zip(fsm.transitions, layout.routes):
                        for a, b in zip(route.points, route.points[1:]):
                            self.assertTrue(abs(a[0] - b[0]) < 0.01
                                            or abs(a[1] - b[1]) < 0.01,
                                            'A transition contains a diagonal segment')
                        if transition.label:
                            self.assertIsNotNone(route.label)

    def test_nonorthogonal_graphviz_fallback_is_rejected(self):
        fsm = Parser().parse('state A\nstate B\nA -> B\n')
        nodes = build_nodes(fsm)
        graph = {'bb': '0,0,100,100', 'edges': [
            {'id': 'edge_0', 'pos': '0,0 100,100'}]}
        with patch('fsmrouting.run_graphviz', return_value=graph):
            with self.assertRaisesRegex(DiagramError, 'non-orthogonal'):
                route_graph(nodes, fsm.transitions, [[]], 'TB')

    def test_exported_transition_labels_stay_on_routes_and_clear_of_boxes(self):
        for direction in ('TB', 'LR'):
            for source in (ALARM, PARALLEL):
                with self.subTest(direction=direction, source=source):
                    fsm = Parser().parse(f'direction: {direction}\n' + source)
                    layout = layout_fsm(fsm)
                    cells = {c.get('id'): c for c in to_xml(fsm, layout).iter('mxCell')}
                    obstacles = [(n.x, n.y, n.x + n.width, n.y + n.height)
                                 for n in layout.nodes.values()]
                    for index, (transition, route) in enumerate(zip(fsm.transitions, layout.routes)):
                        if not transition.label:
                            continue
                        geometry = cells[f'fsm_edge_{index}'].find('mxGeometry')
                        offset = geometry.find("mxPoint[@as='offset']")
                        mid = midpoint(route.points)
                        x, y = mid[0] + float(offset.get('x')), mid[1] + float(offset.get('y'))
                        self.assertTrue(any(
                            min(a[0], b[0]) - 0.01 <= x <= max(a[0], b[0]) + 0.01
                            and min(a[1], b[1]) - 0.01 <= y <= max(a[1], b[1]) + 0.01
                            for a, b in zip(route.points, route.points[1:])),
                            'Exported transition label is detached from its arrow')
                        width, height = label_size(layout.edge_labels[index])
                        box = (x - width / 2, y - height / 2, x + width / 2, y + height / 2)
                        for other in obstacles:
                            self.assertFalse(min(box[2], other[2]) - max(box[0], other[0]) > 0.01
                                             and min(box[3], other[3]) - max(box[1], other[1]) > 0.01,
                                             'Transition label overlaps a state or another label')
                        obstacles.append(box)

    def test_start_precedes_every_state_in_a_cycle_regardless_of_declaration_order(self):
        source = '''state MeasuringBackup
state BackupSettling
state MainSettling
state MeasuringMain
state Idle
BackupSettling -> MeasuringBackup : settled
MainSettling -> Idle : settled
MeasuringMain -> BackupSettling : measurement ready
Idle -> MeasuringMain : start self test
initial -> Idle
MeasuringBackup -> MainSettling : measurement ready
'''
        for direction in ('TB', 'LR'):
            with self.subTest(direction=direction):
                layout = layout_fsm(Parser().parse(f'direction: {direction}\n' + source))
                start = layout.nodes['initial']
                entry = layout.nodes['Idle']
                for name, node in layout.nodes.items():
                    if name == 'initial':
                        continue
                    if direction == 'TB':
                        self.assertLess(start.y + start.height, node.y)
                        if name != 'Idle':
                            self.assertLess(entry.y + entry.height, node.y)
                    else:
                        self.assertLess(start.x + start.width, node.x)
                        if name != 'Idle':
                            self.assertLess(entry.x + entry.width, node.x)

    def test_initial_arrow_stays_short_with_large_transition_spacing(self):
        for direction in ('TB', 'LR'):
            with self.subTest(direction=direction):
                fsm = Parser().parse(f'direction: {direction}\ntransition-spacing: 1000\n' + ALARM)
                layout = layout_fsm(fsm)
                route = layout.routes[0]
                self.assertEqual(len(route.points), 2)
                self.assertAlmostEqual(math.dist(*route.points), 32)
                start = layout.nodes['initial']
                entry = layout.nodes['Disabled']
                if direction == 'TB':
                    self.assertAlmostEqual(start.y, 0)
                    self.assertAlmostEqual(entry.y - start.y - start.height, 32, delta=0.5)
                    self.assertGreater(layout.nodes['Signalling'].y - entry.y - entry.height, 1000)
                else:
                    self.assertAlmostEqual(start.x, 0)
                    self.assertAlmostEqual(entry.x - start.x - start.width, 32, delta=0.5)
                    self.assertGreater(layout.nodes['Signalling'].x - entry.x - entry.width, 1000)

    def test_captions_reposition_to_share_available_space_without_stretching_routes(self):
        routes = [EdgeRoute([(100, 0), (100, 110)], (100, 55)),
                  EdgeRoute([(120, 0), (120, 110)], (120, 55))]
        labels = [['Start', 'StartAction()'], ['Stop', 'StopAction()']]
        measure_texts((line, 11, False) for lines in labels for line in lines)
        positions = place_route_labels(routes, labels, [])
        self.assertIsNotNone(positions)
        first, second = positions[0], positions[1]
        self.assertEqual(first[0], 100)
        self.assertEqual(second[0], 120)
        self.assertGreaterEqual(abs(first[1] - second[1]),
                                (label_size(labels[0])[1] + label_size(labels[1])[1]) / 2 + 4)
        for index, (_, y) in positions.items():
            half_height = label_size(labels[index])[1] / 2
            self.assertGreaterEqual(y, half_height)
            self.assertLessEqual(y, 110 - half_height)

    def test_labeled_initial_arrow_reserves_space_for_its_caption(self):
        for direction in ('TB', 'LR'):
            with self.subTest(direction=direction):
                source = (f'direction: {direction}\ntransition-spacing: 1000\n'
                          'state Idle\ninitial -> Idle : Start /\\nInitialize()\n')
                fsm = Parser().parse(source)
                layout = layout_fsm(fsm)
                route = layout.routes[0]
                axis = 1 if direction == 'TB' else 0
                extent = label_size(layout.edge_labels[0])[axis]
                self.assertGreaterEqual(math.dist(*route.points), extent)
                self.assertLess(math.dist(*route.points), extent + 32)
                self.assertEqual(route.label, midpoint(route.points))


if __name__ == '__main__':
    unittest.main()
