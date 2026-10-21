"""End-to-end tests kept separate from either generator's import namespace."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

VENDOR = Path(__file__).resolve().parent.parent


class AnnotationTest(unittest.TestCase):
    def check(self, language, source):
        proc = subprocess.run([sys.executable, str(VENDOR / (language+'gen') / 'check.py')],
                              input=source, capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)

    def generate(self, language, source):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / ('diagram.'+language)
            src.write_text(source)
            proc = subprocess.run([sys.executable, str(VENDOR / (language+'gen') / 'main.py'), str(src)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return src.with_suffix('.drawio').read_text()

    def test_forward_targets_multiline_escaped_text_and_determinism(self):
        for language, declaration, target in [('cls', 'class Service', 'Service'), ('fsm', 'state Idle', 'Idle')]:
            with self.subTest(language=language):
                source = f'note on {target} width 180: a < b && c > d\\nSecond line\n{declaration}\n'
                self.assertEqual(self.check(language, source), [])
                output = self.generate(language, source)
                self.assertEqual(output, self.generate(language, source))
                cells = list(ET.fromstring(output).iter('mxCell'))
                note = next(c for c in cells if 'shape=note;' in c.get('style', ''))
                self.assertEqual(note.get('value'), 'a &lt; b &amp;&amp; c &gt; d<br>Second line')
                self.assertEqual(float(note.find('mxGeometry').get('width')), 180)
                link = next(c for c in cells if c.get('target') == note.get('id'))
                self.assertEqual(link.get('source'), language+'_'+target)
                self.assertIn('dashed=1;', link.get('style'))

    def test_unknown_note_target_has_source_line(self):
        for language, declaration in [('cls', 'class A'), ('fsm', 'state A')]:
            errors = self.check(language, declaration+'\nnote on Missing: why\n')
            self.assertEqual(errors, [{'line': 2, 'col': 1, 'message': 'Unknown note target "Missing"'}])

    def test_invalid_width_and_empty_note_are_rejected(self):
        for language, declaration in [('cls', 'class A'), ('fsm', 'state A')]:
            for width in (-1, 0, 79, 1001):
                errors = self.check(language, f'{declaration}\nnote on A width {width}: text\n')
                self.assertEqual(errors[0]['line'], 2)
                self.assertIn('Note width', errors[0]['message'])
            self.assertTrue(self.check(language, declaration+'\nnote on A:\n'))
            self.assertTrue(self.check(language, declaration+'\nnote on A:   \n'))

    def test_pseudostates_must_be_drawn_and_choices_can_have_notes(self):
        self.assertTrue(self.check('fsm', 'state A\nnote on initial: missing\n'))
        source = ('state A\nchoice Decide\ninitial -> A\nA -> Decide\nDecide -> final\n'
                  'note on initial: start\nnote on Decide: check\nnote on final: end\n')
        self.assertEqual(self.check('fsm', source), [])
        cells = list(ET.fromstring(self.generate('fsm', source)).iter('mxCell'))
        self.assertEqual(sum('shape=note;' in c.get('style', '') for c in cells), 3)

    def test_nested_class_container_targets_and_multiple_notes(self):
        source = ('package P {\n component C {\n  class A\n  interface I\n  A ..|> I\n'
                  '  note on A: first\n }\n}\n'
                  'note on P: package\nnote on C: component\nnote on A: second\n')
        self.assertEqual(self.check('cls', source), [])
        self.assert_geometry('cls', self.generate('cls', source))

    def test_notes_dont_move_existing_vertices_or_edges(self):
        for language, source in [('cls', 'class A\nclass B\nA --> B\n'),
                                 ('fsm', 'state A\nstate B\ninitial -> A\nA -> B\n')]:
            def normalized(cell):
                for element in cell.iter():
                    element.tail = None
                    if element.text and element.text.isspace():
                        element.text = None
                return ET.tostring(cell)
            plain = {c.get('id'): normalized(c) for c in ET.fromstring(self.generate(language, source)).iter('mxCell')}
            annotated = self.generate(language, source+'note on A: explanation\nnote on B: more\n')
            for cell in ET.fromstring(annotated).iter('mxCell'):
                if cell.get('id') in plain and cell.get('id') != language+'_frame':
                    self.assertEqual(normalized(cell), plain[cell.get('id')])
            self.assert_geometry(language, annotated)

    def test_long_notes_auto_grow_and_crlf_without_final_newline(self):
        for language, declaration in [('cls', 'class A'), ('fsm', 'state A')]:
            source = declaration+'\r\nnote on A width 80: '+('a long note '*20)
            output = self.generate(language, source)
            note = next(c for c in ET.fromstring(output).iter('mxCell') if 'shape=note;' in c.get('style', ''))
            self.assertGreater(float(note.find('mxGeometry').get('height')), 56)
            self.assert_geometry(language, output)

    def test_narrow_notes_wrap_wide_unbroken_identifiers(self):
        output = self.generate('cls', 'class A\nnote on A width 80: ' + 'W'*40 + '\n')
        note = next(c for c in ET.fromstring(output).iter('mxCell') if 'shape=note;' in c.get('style', ''))
        lines = note.get('value').split('<br>')
        self.assertEqual(''.join(lines), 'W'*40)
        self.assertTrue(all(len(line) <= 4 for line in lines))
        self.assertEqual(float(note.find('mxGeometry').get('height')), 24 + len(lines)*16)

    def assert_geometry(self, language, output):
        cells = {c.get('id'): c for c in ET.fromstring(output).iter('mxCell')}
        self.assertEqual(len(cells), len(list(ET.fromstring(output).iter('mxCell'))))
        frame = cells[language+'_frame'].find('mxGeometry')
        fw, fh = float(frame.get('width')), float(frame.get('height'))
        def rect(cell):
            g = cell.find('mxGeometry')
            x, y = float(g.get('x', 0)), float(g.get('y', 0))
            if cell.get('parent') not in ('0', '1'):
                px, py, _, _ = rect(cells[cell.get('parent')])
                x, y = x+px, y+py
            return x, y, float(g.get('width')), float(g.get('height'))
        notes = [c for c in cells.values() if 'shape=note;' in c.get('style', '')]
        for note in notes:
            x, y, w, h = rect(note)
            self.assertTrue(0 <= x < x+w <= fw and 0 <= y < y+h <= fh)
            for cell in cells.values():
                if cell == note or cell.get('vertex') != '1' or cell.get('id') == language+'_frame':
                    continue
                if cell.find('mxGeometry').get('relative') == '1':
                    continue
                ox, oy, ow, oh = rect(cell)
                self.assertFalse(x < ox+ow and x+w > ox and y < oy+oh and y+h > oy)
        for link in (c for c in cells.values() if '$note_link_' in c.get('id','')):
            self.assertIn(link.get('source'), cells)
            self.assertIn(link.get('target'), cells)
            source = cells[link.get('source')]
            target = cells[link.get('target')]
            sx, sy, sw, sh = rect(source)
            tx, ty, _, th = rect(target)
            style = dict(part.split('=',1) for part in link.get('style').split(';') if '=' in part)
            points = [(sx + sw*float(style['exitX']), sy + sh*float(style['exitY']))]
            points += [(float(p.get('x')),float(p.get('y'))) for p in link.findall('mxGeometry/Array/mxPoint')]
            points += [(tx,ty+th/2)]
            for a,b in zip(points,points[1:]):
                self.assertTrue(abs(a[0]-b[0]) < .001 or abs(a[1]-b[1]) < .001)
                self.assertTrue(all(0 <= x <= fw and 0 <= y <= fh for x,y in (a,b)))
                for cell in cells.values():
                    if cell.get('parent') != '1' or cell.get('vertex') != '1':
                        continue
                    if cell.get('id') in (language+'_frame', link.get('source')):
                        continue
                    # A target's containing package is deliberately traversable.
                    parent = source.get('parent')
                    parents = []
                    while parent not in ('0','1'):
                        parents.append(parent)
                        parent = cells[parent].get('parent')
                    if cell.get('id') in parents:
                        continue
                    x,y,w,h = rect(cell)
                    if abs(a[0]-b[0]) < .001:
                        hit = x+.001 < a[0] < x+w-.001 and max(a[1],b[1]) > y+.001 and min(a[1],b[1]) < y+h-.001
                    else:
                        hit = y+.001 < a[1] < y+h-.001 and max(a[0],b[0]) > x+.001 and min(a[0],b[0]) < x+w-.001
                    self.assertFalse(hit, (link.get('id'), cell.get('id'), a, b))


if __name__ == '__main__':
    unittest.main()
