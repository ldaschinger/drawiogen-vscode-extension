"""Regression cases for overlapping forward, return, parallel and loop arrows."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsmast import Parser
from layout import layout_fsm
from drawio_out import to_xml


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
        self.assertGreater(max(x for x, _ in loop.points), node.x + node.width + 20)
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


if __name__ == '__main__':
    unittest.main()
