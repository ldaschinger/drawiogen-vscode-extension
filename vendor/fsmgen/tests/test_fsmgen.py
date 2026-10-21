import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
FSMGEN = os.path.dirname(HERE)
sys.path.insert(0, FSMGEN)

from fsmast import Parser, FsmError  # noqa: E402

MAIN = os.path.join(FSMGEN, 'main.py')
CHECK = os.path.join(FSMGEN, 'check.py')
EXAMPLE = os.path.join(FSMGEN, 'examples', 'Workflow.fsm')

MINIMAL = '''title: Minimal
initial -> Idle
state Idle {
  entry: Start()
  on Tick: Count()
}
state Busy : Busy state
Idle -> Busy: Go [ready] / Run()
Busy -> final
'''


def generate(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'a.fsm'), os.path.join(tmp, 'a.drawio')
        with open(src, 'w') as f:
            f.write(source)
        proc = subprocess.run([sys.executable, MAIN, src, '-o', out], stderr=subprocess.PIPE)
        content = open(out).read() if os.path.exists(out) else None
        return proc.returncode, proc.stderr.decode(), content


def cells_by_id(out: str):
    return {c.get('id'): c for c in ET.fromstring(out).iter('mxCell')}


def check(source: str):
    proc = subprocess.run([sys.executable, CHECK], input=source.encode(), stdout=subprocess.PIPE)
    return json.loads(proc.stdout)


class ParserTest(unittest.TestCase):
    def test_parses_states_choices_and_transitions(self):
        fsm = Parser().parse(MINIMAL)
        self.assertEqual(fsm.title, 'Minimal')
        self.assertEqual(list(fsm.states), ['Idle', 'Busy'])
        self.assertEqual(fsm.states['Busy'].label, 'Busy state')
        self.assertEqual(fsm.states['Idle'].entry, ['Start()'])
        self.assertEqual(fsm.states['Idle'].internal, [('Tick', 'Count()')])
        self.assertEqual(len(fsm.transitions), 3)
        self.assertEqual(fsm.transitions[1].label, 'Go [ready] / Run()')

    def test_comments_and_blank_lines_ignored(self):
        fsm = Parser().parse('// c\n\nstate A\n\n// d\n')
        self.assertEqual(list(fsm.states), ['A'])

    def test_unknown_state_reports_line(self):
        with self.assertRaises(FsmError) as ctx:
            Parser().parse('state A\nA -> B\n')
        self.assertEqual(ctx.exception.line, 2)
        self.assertIn('Unknown state "B"', str(ctx.exception))

    def test_duplicate_state(self):
        with self.assertRaises(FsmError):
            Parser().parse('state A\nstate A\n')

    def test_reserved_name(self):
        with self.assertRaises(FsmError):
            Parser().parse('state initial\n')

    def test_two_initial_transitions_rejected(self):
        with self.assertRaises(FsmError):
            Parser().parse('state A\ninitial -> A\ninitial -> A\n')


class CheckScriptTest(unittest.TestCase):
    def test_valid_input_has_no_errors(self):
        self.assertEqual(check(MINIMAL), [])

    def test_syntax_error_has_position(self):
        errors = check('state A\nbogus line here\n')
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['line'], 2)

    def test_semantic_error_has_line(self):
        errors = check('state A\nA -> Missing\n')
        self.assertEqual(errors, [{'line': 2, 'col': 1, 'message': 'Unknown state "Missing"'}])


class GeneratorTest(unittest.TestCase):
    def test_output_is_valid_drawio_xml(self):
        code, err, out = generate(MINIMAL)
        self.assertEqual(code, 0, err)
        root = ET.fromstring(out)
        self.assertEqual(root.tag, 'mxfile')
        ids = [c.get('id') for c in root.iter('mxCell')]
        self.assertEqual(len(ids), len(set(ids)), 'duplicate cell ids')

    def test_every_node_and_edge_is_emitted(self):
        _, _, out = generate(MINIMAL)
        cells = {c.get('id'): c for c in ET.fromstring(out).iter('mxCell')}
        for name in ('fsm_Idle', 'fsm_Busy', 'fsm_initial', 'fsm_final'):
            self.assertIn(name, cells)
        self.assertEqual(sum(1 for c in cells.values() if c.get('edge') == '1'), 3)

    def test_edges_reference_existing_cells(self):
        _, _, out = generate(MINIMAL)
        cells = {c.get('id'): c for c in ET.fromstring(out).iter('mxCell')}
        for c in cells.values():
            if c.get('edge') == '1':
                self.assertIn(c.get('source'), cells)
                self.assertIn(c.get('target'), cells)

    def test_nodes_do_not_overlap(self):
        _, _, out = generate(open(EXAMPLE).read())
        boxes = []
        for c in ET.fromstring(out).iter('mxCell'):
            if c.get('vertex') == '1' and c.get('id') != 'fsm_frame':
                g = c.find('mxGeometry')
                x, y, w, h = (float(g.get(k)) for k in ('x', 'y', 'width', 'height'))
                boxes.append((c.get('id'), x, y, x + w, y + h))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap = a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]
                self.assertFalse(overlap, f'{a[0]} overlaps {b[0]}')

    def test_body_uses_small_font_and_title_is_bold(self):
        _, _, out = generate(MINIMAL)
        value = cells_by_id(out)['fsm_Idle'].get('value')
        self.assertIn('<b><font style="font-size:12px">Idle</font></b>', value)
        self.assertIn('<font style="font-size:10px">', value)

    def test_entry_exit_and_events_are_grouped_by_blank_lines(self):
        _, _, out = generate('state A {\n  entry: e1()\n  entry: e2()\n  exit: x()\n  on Ev: act()\n}\n')
        value = cells_by_id(out)['fsm_A'].get('value')
        body = value.split('<font style="font-size:10px">')[1].split('</font>')[0]
        nb = '&nbsp;' * 4
        self.assertEqual(body, f'Entry:<br>{nb}e1()<br>{nb}e2()<br><br>Exit:<br>{nb}x()<br><br>Event Ev: act()')

    def test_state_without_body_has_no_separator(self):
        _, _, out = generate('state A\n')
        self.assertNotIn('<hr', cells_by_id(out)['fsm_A'].get('value'))

    def test_output_is_deterministic(self):
        first = generate(open(EXAMPLE).read())[2]
        second = generate(open(EXAMPLE).read())[2]
        self.assertEqual(first, second)

    def test_special_characters_are_escaped(self):
        code, err, out = generate('state A {\n  on E: if (a < b && c > d) x = "y"\n}\n')
        self.assertEqual(code, 0, err)
        ET.fromstring(out)

    def test_direction_lr_changes_layout(self):
        base = 'state A\nstate B\nA -> B\n'
        _, _, tb = generate(base)
        _, _, lr = generate('direction: LR\n' + base)

        def pos(out, id_):
            g = [c for c in ET.fromstring(out).iter('mxCell') if c.get('id') == id_][0].find('mxGeometry')
            return float(g.get('x')), float(g.get('y'))

        self.assertGreater(pos(tb, 'fsm_B')[1], pos(tb, 'fsm_A')[1])
        self.assertGreater(pos(lr, 'fsm_B')[0], pos(lr, 'fsm_A')[0])

    def test_error_exits_nonzero_with_line(self):
        code, err, out = generate('state A\nA -> Missing\n')
        self.assertNotEqual(code, 0)
        self.assertIn(':2:', err)
        self.assertIsNone(out)


if __name__ == '__main__':
    unittest.main()
