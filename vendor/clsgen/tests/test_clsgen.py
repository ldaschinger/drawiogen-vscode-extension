import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CLSGEN = os.path.dirname(HERE)
sys.path.insert(0, CLSGEN)

from clsast import Parser, ClsError  # noqa: E402

MAIN = os.path.join(CLSGEN, 'main.py')
CHECK = os.path.join(CLSGEN, 'check.py')
EXAMPLES = os.path.join(CLSGEN, 'examples')

CLASSES = '''title: Demo
interface IFoo {
  + vDo()
}
class Foo <<object>> {
  - nCount: int
  + vDo()
  + nGet(): int
}
enum Mode : Operating mode {
  Idle
  Busy = 1
}
class Bar
Foo ..|> IFoo
Foo *-- "1" Bar : owns
Foo --> "0..*" Mode
'''

NESTED = '''package P {
  component C : Comp {
    interface I
    class K
  }
  component Other
}
K ..|> I
Other ..> I
'''

TWO_PACKAGES = NESTED + '''package External {
  component Library
}
K ..> Library
'''


def read(path):
    with open(path) as f:
        return f.read()


def generate(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, 'a.cls'), os.path.join(tmp, 'a.drawio')
        with open(src, 'w') as f:
            f.write(source)
        proc = subprocess.run([sys.executable, MAIN, src, '-o', out], stderr=subprocess.PIPE)
        content = read(out) if os.path.exists(out) else None
        return proc.returncode, proc.stderr.decode(), content


def check(source: str):
    proc = subprocess.run([sys.executable, CHECK], input=source.encode(), stdout=subprocess.PIPE)
    return json.loads(proc.stdout)


def cells_of(out: str):
    return {c.get('id'): c for c in ET.fromstring(out).iter('mxCell')}


def absolute_box(cells, c):
    g = c.find('mxGeometry')
    x, y, w, h = (float(g.get(k)) for k in ('x', 'y', 'width', 'height'))
    p = cells.get(c.get('parent'))
    while p is not None and p.get('vertex') == '1':
        pg = p.find('mxGeometry')
        x, y = x + float(pg.get('x')), y + float(pg.get('y'))
        p = cells.get(p.get('parent'))
    return x, y, x + w, y + h


class ParserTest(unittest.TestCase):
    def test_classifiers_members_and_defaults(self):
        cls = Parser().parse(CLASSES)
        foo = cls.elements['Foo']
        self.assertEqual(foo.stereotype, 'object')
        self.assertEqual([(m.visibility, m.text, m.is_method) for m in foo.members],
                         [('-', 'nCount: int', False), ('+', 'vDo()', True), ('+', 'nGet(): int', True)])
        self.assertEqual(cls.elements['IFoo'].stereotype, 'interface')
        self.assertEqual(cls.elements['Mode'].stereotype, 'enumeration')
        self.assertEqual(cls.elements['Mode'].label, 'Operating mode')
        self.assertEqual([m.text for m in cls.elements['Mode'].members], ['Idle', 'Busy = 1'])

    def test_relations_with_multiplicity_and_label(self):
        rel = Parser().parse(CLASSES).relations
        self.assertEqual((rel[1].arrow, rel[1].src_mult, rel[1].label), ('*--', None, 'owns'))
        self.assertEqual(rel[1].tgt_mult, '1')
        self.assertEqual((rel[2].arrow, rel[2].tgt_mult), ('-->', '0..*'))

    def test_nesting(self):
        cls = Parser().parse(NESTED)
        self.assertEqual([e.id for e in cls.roots], ['P'])
        self.assertEqual(cls.elements['K'].parent, 'C')
        self.assertEqual(cls.elements['C'].parent, 'P')
        self.assertTrue(cls.elements['C'].is_container)
        self.assertFalse(cls.elements['Other'].is_container)

    def test_comments_ignored(self):
        cls = Parser().parse('// x\nclass A\n\n// y\n')
        self.assertEqual(list(cls.elements), ['A'])

    def test_unknown_element_reports_line(self):
        with self.assertRaises(ClsError) as ctx:
            Parser().parse('class A\nA --> B\n')
        self.assertEqual(ctx.exception.line, 2)

    def test_duplicate_element(self):
        with self.assertRaises(ClsError):
            Parser().parse('class A\ncomponent A\n')

    def test_relation_to_container_rejected(self):
        with self.assertRaises(ClsError):
            Parser().parse('package P {\n  class A\n}\nclass B\nB --> P\n')

    def test_empty_container_rejected(self):
        with self.assertRaises(ClsError):
            Parser().parse('package P {\n}\n')

    def test_member_without_visibility_rejected(self):
        with self.assertRaises(ClsError):
            Parser().parse('class A {\n  nope\n}\n')

    def test_enum_literal_with_visibility_rejected(self):
        with self.assertRaises(ClsError):
            Parser().parse('enum E {\n  + X\n}\n')


class CheckScriptTest(unittest.TestCase):
    def test_top_row_reports_invalid_scope_and_names(self):
        cases = [
            ('top-row: A B\nclass A\nclass B\n', 'belongs inside'),
            ('component C {\ntop-row: A Missing\nclass A\n}\n', 'Unknown element "Missing"'),
            ('component C {\ntop-row: A A\nclass A\n}\n', 'distinct elements'),
            ('component C {\ntop-row: A B\nclass A\n}\nclass B\n', 'direct leaf children'),
            ('component C {\ntop-row: A B\nclass A\ncomponent B {\nclass K\n}\n}\n',
             'direct leaf children'),
            ('direction: LR\ncomponent C {\ntop-row: A B\nclass A\nclass B\n}\n',
             'requires direction: TB'),
            ('component C {\ntop-row: A B\ntop-row: A B\nclass A\nclass B\n}\n',
             'only one top-row'),
        ]
        for source, message in cases:
            with self.subTest(message=message):
                errors = check(source)
                self.assertEqual(len(errors), 1)
                self.assertIn(message, errors[0]['message'])

    def test_layout_group_errors_have_source_lines(self):
        cases = [
            ('same-size: P Missing\narrange: LR\n' + TWO_PACKAGES,
             'Unknown element "Missing"'),
            ('same-size: P External\n' + TWO_PACKAGES, 'same-size requires arrange'),
            ('arrange: LR\nsame-size: C External\n' + TWO_PACKAGES,
             'same-size names top-level'),
            ('arrange: TB\nalign-horizontal: K Library\n' + TWO_PACKAGES,
             'align-horizontal requires arrange: LR'),
            ('arrange: LR\nalign-horizontal: I K\n' + TWO_PACKAGES,
             'must be in separate top-level blocks'),
            ('arrange: LR\nsame-size: P P\n' + TWO_PACKAGES,
             'must name distinct elements'),
            ('package P {\n  same-size: A B\n  component A\n  component B\n}\n',
             'only supported at the top level'),
        ]
        for source, message in cases:
            with self.subTest(message=message):
                errors = check(source)
                self.assertEqual(len(errors), 1)
                self.assertIn(message, errors[0]['message'])
                self.assertIn(errors[0]['line'], (1, 2))

    def test_valid_input(self):
        self.assertEqual(check(CLASSES), [])

    def test_syntax_error_position(self):
        errors = check('class A\n???\n')
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['line'], 2)

    def test_semantic_error(self):
        errors = check('class A\nA --> B\n')
        self.assertEqual(errors, [{'line': 2, 'col': 1, 'message': 'Unknown element "B"'}])

    def test_nested_arrange_reports_unsupported_scope(self):
        errors = check('package P {\n  arrange: LR\n  class A\n}\n')
        self.assertEqual(errors, [{'line': 2, 'col': 1,
                                  'message': 'arrange is only supported at the top level'}])


class GeneratorTest(unittest.TestCase):
    def test_top_row_keeps_interfaces_above_interdependent_implementations(self):
        for kind in ('package', 'component'):
            with self.subTest(kind=kind):
                source = kind + ''' C {
  top-row: IA IB IC
  interface IA
  class A
  interface IB
  class B
  interface IC
  class K
}
A ..|> IA
B ..|> IB
K ..|> IC
A ..> B
B ..> K
'''
                code, err, out = generate(source)
                self.assertEqual(code, 0, err)
                cells = cells_of(out)
                interfaces = [absolute_box(cells, cells['cls_' + n]) for n in ('IA', 'IB', 'IC')]
                self.assertEqual(len({b[1] for b in interfaces}), 1)
                for name in ('A', 'B', 'K'):
                    self.assertLess(max(b[3] for b in interfaces),
                                    absolute_box(cells, cells['cls_' + name])[1])
                parent = absolute_box(cells, cells['cls_C'])
                for box in interfaces:
                    self.assertTrue(parent[0] <= box[0] < box[2] <= parent[2])
                    self.assertGreater(box[1], parent[1])
                ordered = sorted(interfaces)
                for a, b in zip(ordered, ordered[1:]):
                    self.assertLess(a[2], b[0])
                self.assertEqual(out, generate(source)[2])

    def test_component_children_centered_in_body_below_title(self):
        sources = [
            ('component C {\n  interface I\n  class K\n}\nK ..|> I\n', ('C',)),
            ('package P {\n  component C {\n    component Inner {\n'
             '      interface I\n      class K\n    }\n  }\n}\nK ..|> I\n',
             ('C', 'Inner')),
        ]
        for source, names in sources:
            code, err, out = generate(source)
            self.assertEqual(code, 0, err)
            cells = cells_of(out)
            for name in names:
                with self.subTest(component=name):
                    parent = absolute_box(cells, cells['cls_' + name])
                    children = [absolute_box(cells, c) for c in cells.values()
                                if c.get('parent') == 'cls_' + name and c.get('vertex') == '1'
                                and not c.get('id').endswith('_icon')]
                    left, top = min(c[0] for c in children), min(c[1] for c in children)
                    right, bottom = max(c[2] for c in children), max(c[3] for c in children)
                    self.assertAlmostEqual(left - parent[0], parent[2] - right)
                    self.assertAlmostEqual(top - (parent[1] + 26), parent[3] - bottom)
                    self.assertGreaterEqual(top, parent[1] + 26)

    def test_inner_boxes_default_to_largest_sibling_width_and_height(self):
        source = '''component C {
  interface I {
    + first()
    + second()
    + third()
  }
  class A_rather_long_implementation_name
}
A_rather_long_implementation_name ..|> I
'''
        code, err, out = generate(source)
        self.assertEqual(code, 0, err)
        cells = cells_of(out)
        interface = absolute_box(cells, cells['cls_I'])
        implementation = absolute_box(cells, cells['cls_A_rather_long_implementation_name'])
        dims = lambda b: (b[2] - b[0], b[3] - b[1])
        self.assertEqual(dims(interface), dims(implementation))
        # The wide name and tall member list must both fit without shrinking either.
        self.assertGreaterEqual(dims(interface)[0], len('A_rather_long_implementation_name') * 8)
        self.assertGreaterEqual(dims(interface)[1], 42 + 8 + 3 * 20)
        self.assertLess(interface[3], implementation[1])
        container = absolute_box(cells, cells['cls_C'])
        self.assertTrue(container[0] <= interface[0] < interface[2] <= container[2])
        self.assertLessEqual(implementation[3], container[3])

    def test_default_inner_sizing_is_local_to_each_container(self):
        source = '''package P {
  component Large {
    interface A
    class A_very_long_class_name_to_make_this_component_wider
  }
  component Small {
    interface B
    class K
  }
  component Standalone
}
'''
        code, err, out = generate(source)
        self.assertEqual(code, 0, err)
        cells = cells_of(out)
        width = lambda n: float(cells['cls_' + n].find('mxGeometry').get('width'))
        self.assertEqual(width('A'), width('A_very_long_class_name_to_make_this_component_wider'))
        self.assertEqual(width('B'), width('K'))
        self.assertGreater(width('A'), width('B'))
        self.assertLess(width('Standalone'), width('Large'))

    def test_equal_blocks_and_horizontal_dependency_preserve_vertical_inheritance(self):
        source = ('arrange: LR\nsame-size: P External\nalign-horizontal: K Library\n'
                  + TWO_PACKAGES)
        code, err, out = generate(source)
        self.assertEqual(code, 0, err)
        cells = cells_of(out)
        a = absolute_box(cells, cells['cls_P'])
        b = absolute_box(cells, cells['cls_External'])
        self.assertEqual((a[2] - a[0], a[3] - a[1]), (b[2] - b[0], b[3] - b[1]))
        self.assertEqual(a[1], b[1])
        self.assertLess(a[2], b[0])
        k = absolute_box(cells, cells['cls_K'])
        lib = absolute_box(cells, cells['cls_Library'])
        self.assertEqual((k[1] + k[3]) / 2, (lib[1] + lib[3]) / 2)
        self.assertLess(absolute_box(cells, cells['cls_I'])[3], k[1])
        self.assertIn('exitX=1;exitY=0.5', cells['cls_edge_2'].get('style'))
        self.assertIn('entryX=0;entryY=0.5', cells['cls_edge_2'].get('style'))
        self.assertIn('exitY=0;', cells['cls_edge_0'].get('style'))
        self.assertIn('entryY=1;', cells['cls_edge_0'].get('style'))
        for c in cells.values():
            parent = cells.get(c.get('parent'))
            if c.get('vertex') == '1' and parent is not None and parent.get('vertex') == '1' \
                    and not c.get('id').endswith('_icon'):
                box = absolute_box(cells, c)
                bounds = absolute_box(cells, parent)
                self.assertTrue(bounds[0] <= box[0] < box[2] <= bounds[2])
                self.assertTrue(bounds[1] <= box[1] < box[3] <= bounds[3])
        self.assertEqual(out, generate(source)[2])

    def test_same_size_works_for_stacked_blocks(self):
        code, err, out = generate('arrange: TB\nsame-size: P External\n' + TWO_PACKAGES)
        self.assertEqual(code, 0, err)
        cells = cells_of(out)
        a = absolute_box(cells, cells['cls_P'])
        b = absolute_box(cells, cells['cls_External'])
        self.assertEqual((a[2] - a[0], a[3] - a[1]), (b[2] - b[0], b[3] - b[1]))
        self.assertLess(a[3], b[1])

    def test_overlapping_same_size_groups_propagate(self):
        source = ('arrange: LR\nsame-size: P External\nsame-size: External Third\n'
                  + TWO_PACKAGES + 'package Third {\n  component HugeNameForSizingTheBlock\n}\n')
        code, err, out = generate(source)
        self.assertEqual(code, 0, err)
        cells = cells_of(out)
        sizes = [tuple(cells['cls_' + n].find('mxGeometry').get(k)
                       for k in ('width', 'height')) for n in ('P', 'External', 'Third')]
        self.assertEqual(sizes[0], sizes[1])
        self.assertEqual(sizes[1], sizes[2])

    def test_horizontal_alignment_moves_nested_branch_and_lower_siblings(self):
        source = '''arrange: LR
align-horizontal: K Library
package P {
  component C {
    interface I
    class K
  }
  component Tail
}
package External {
  component Upper
  component Library
}
K ..|> I
K ..> Library
Library ..> Tail
Upper ..> Library
K ..> Tail
'''
        # Aligning I also exercises moving the whole nested component branch down.
        _, _, original = generate(source.replace('align-horizontal: K Library\n', ''))
        before = cells_of(original)
        for names in ('K Library', 'Library I'):
            with self.subTest(names=names):
                code, err, out = generate(source.replace('K Library', names))
                self.assertEqual(code, 0, err)
                cells = cells_of(out)
                c = absolute_box(cells, cells['cls_C'])
                tail = absolute_box(cells, cells['cls_Tail'])
                self.assertLess(c[3], tail[1])
                p = absolute_box(cells, cells['cls_P'])
                self.assertLessEqual(tail[3], p[3])
                if names == 'Library I':
                    self.assertGreater(float(cells['cls_C'].find('mxGeometry').get('y')),
                                       float(before['cls_C'].find('mxGeometry').get('y')))
                first, second = (absolute_box(cells, cells['cls_' + n]) for n in names.split())
                self.assertEqual((first[1] + first[3]) / 2, (second[1] + second[3]) / 2)

    def test_arrange_places_packages_in_requested_direction(self):
        for direction in ('LR', 'TB'):
            with self.subTest(direction=direction):
                code, err, out = generate(f'arrange: {direction}\n' + TWO_PACKAGES)
                self.assertEqual(code, 0, err)
                cells = cells_of(out)
                a = absolute_box(cells, cells['cls_P'])
                b = absolute_box(cells, cells['cls_External'])
                if direction == 'LR':
                    self.assertEqual(a[1], b[1])
                    self.assertLess(a[2], b[0])
                else:
                    self.assertEqual(a[0], b[0])
                    self.assertLess(a[3], b[1])
                # Keeping packages horizontal must leave inheritance vertical inside them.
                self.assertLess(absolute_box(cells, cells['cls_I'])[3],
                                absolute_box(cells, cells['cls_K'])[1])
                self.assertEqual(cells['cls_edge_2'].get('source'), 'cls_K')
                self.assertEqual(cells['cls_edge_2'].get('target'), 'cls_Library')

    def test_arrange_preserves_nested_geometry_and_contains_all_roots(self):
        _, _, original = generate(TWO_PACKAGES)
        before = cells_of(original)
        for direction in ('LR', 'TB'):
            with self.subTest(direction=direction):
                _, _, out = generate(f'arrange: {direction}\n' + TWO_PACKAGES)
                cells = cells_of(out)
                for id_ in ('cls_C', 'cls_I', 'cls_K', 'cls_Other', 'cls_Library'):
                    self.assertEqual(cells[id_].find('mxGeometry').attrib,
                                     before[id_].find('mxGeometry').attrib)
                frame = absolute_box(cells, cells['cls_frame'])
                for id_ in ('cls_P', 'cls_External'):
                    box = absolute_box(cells, cells[id_])
                    self.assertTrue(frame[0] <= box[0] < box[2] <= frame[2])
                    self.assertTrue(frame[1] <= box[1] < box[3] <= frame[3])
                self.assertEqual(out, generate(f'arrange: {direction}\n' + TWO_PACKAGES)[2])

    def test_valid_xml_unique_ids(self):
        code, err, out = generate(CLASSES)
        self.assertEqual(code, 0, err)
        ids = [c.get('id') for c in ET.fromstring(out).iter('mxCell')]
        self.assertEqual(len(ids), len(set(ids)))

    def test_member_cells_are_children_of_class(self):
        _, _, out = generate(CLASSES)
        cells = cells_of(out)
        rows = [c for c in cells.values() if c.get('parent') == 'cls_Foo']
        values = [c.get('value') for c in rows]
        self.assertEqual(values[:1], ['- nCount: int'])
        self.assertIn('+ nGet(): int', values)
        self.assertEqual(sum(1 for c in rows if 'line;' in c.get('style')), 1)  # divider

    def test_edge_styles_follow_arrow_type(self):
        _, _, out = generate(CLASSES)
        cells = cells_of(out)
        self.assertIn('dashed=1', cells['cls_edge_0'].get('style'))        # realization
        self.assertIn('endFill=0', cells['cls_edge_0'].get('style'))
        self.assertIn('startArrow=diamondThin', cells['cls_edge_1'].get('style'))
        self.assertIn('startFill=1', cells['cls_edge_1'].get('style'))     # composition
        self.assertIn('endArrow=open', cells['cls_edge_2'].get('style'))

    def test_multiplicity_labels_attached_to_edge(self):
        _, _, out = generate(CLASSES)
        cells = cells_of(out)
        self.assertEqual(cells['cls_edge_1_tgt'].get('parent'), 'cls_edge_1')
        self.assertEqual(cells['cls_edge_1_tgt'].get('value'), '1')

    def test_parent_is_laid_out_above_child_for_inheritance(self):
        _, _, out = generate('class Child\nclass Parent\nChild --|> Parent\n')
        cells = cells_of(out)
        self.assertLess(absolute_box(cells, cells['cls_Parent'])[1],
                        absolute_box(cells, cells['cls_Child'])[1])

    def test_children_inside_container_bounds(self):
        _, _, out = generate(NESTED)
        cells = cells_of(out)
        for c in cells.values():
            parent = cells.get(c.get('parent'))
            if c.get('vertex') == '1' and parent is not None and parent.get('vertex') == '1' \
                    and 'line;' not in c.get('style') and 'text;' not in c.get('style') \
                    and not c.get('id').endswith('_icon'):
                a, p = absolute_box(cells, c), absolute_box(cells, parent)
                self.assertTrue(p[0] <= a[0] and p[1] <= a[1] and a[2] <= p[2] and a[3] <= p[3],
                                f'{c.get("id")} outside {parent.get("id")}')

    def test_container_title_has_room(self):
        _, _, out = generate(NESTED)
        cells = cells_of(out)
        for c in cells.values():
            parent = cells.get(c.get('parent'))
            if c.get('vertex') == '1' and parent is not None and parent.get('vertex') == '1' \
                    and 'line;' not in c.get('style') and 'text;' not in c.get('style') \
                    and not c.get('id').endswith('_icon'):
                self.assertGreaterEqual(float(c.find('mxGeometry').get('y')), 30)

    def test_every_component_has_corner_icon(self):
        _, _, out = generate(NESTED)
        cells = cells_of(out)
        for id_ in ('cls_C', 'cls_Other'):
            icon = cells[id_ + '_icon']
            self.assertEqual(icon.get('parent'), id_)
            self.assertIn('shape=module', icon.get('style'))
            geometry = icon.find('mxGeometry')
            self.assertEqual((geometry.get('x'), geometry.get('relative')), ('1', '1'))
        self.assertNotIn('cls_P_icon', cells)           # packages have no component icon
        self.assertNotIn('cls_K_icon', cells)           # neither do classes

    def test_component_header_is_a_swimlane(self):
        _, _, out = generate(NESTED)
        style = cells_of(out)['cls_Other'].get('style')
        self.assertIn('swimlane', style)
        self.assertIn('startSize=26', style)

    def test_package_name_sits_in_tab_wide_enough_for_it(self):
        _, _, out = generate('package A_rather_long_package_name {\n  class X\n}\npackage S {\n  class Y\n}\n')
        cells = cells_of(out)

        def tab(id_):
            style = dict(p.split('=') for p in cells[id_].get('style').split(';') if '=' in p)
            return int(style['tabWidth']), int(style['tabHeight'])

        long_w, height = tab('cls_A_rather_long_package_name')
        short_w, _ = tab('cls_S')
        self.assertGreater(long_w, short_w)
        self.assertGreaterEqual(long_w, len('A_rather_long_package_name') * 7)
        self.assertGreaterEqual(height, 24)
        self.assertEqual(cells['cls_S'].get('value'), 'S')
        self.assertIn('verticalAlign=top', cells['cls_S'].get('style'))
        self.assertIn('align=left', cells['cls_S'].get('style'))

    def test_top_level_nodes_do_not_overlap(self):
        for name in sorted(os.listdir(EXAMPLES)):
            _, _, out = generate(read(os.path.join(EXAMPLES, name)))
            cells = cells_of(out)
            boxes = [(c.get('id'), absolute_box(cells, c)) for c in cells.values()
                     if c.get('vertex') == '1' and c.get('parent') == '1' and c.get('id') != 'cls_frame']
            for i, (ia, a) in enumerate(boxes):
                for ib, b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3],
                                     f'{name}: {ia} overlaps {ib}')

    def test_examples_generate_and_are_deterministic(self):
        for name in sorted(os.listdir(EXAMPLES)):
            source = read(os.path.join(EXAMPLES, name))
            code, err, first = generate(source)
            self.assertEqual(code, 0, f'{name}: {err}')
            self.assertEqual(first, generate(source)[2], f'{name} is not deterministic')

    def test_special_characters_escaped(self):
        code, err, out = generate('class A {\n  + vF(a: List<int>&): bool\n}\n')
        self.assertEqual(code, 0, err)
        ET.fromstring(out)

    def test_error_exits_nonzero_with_line(self):
        code, err, out = generate('class A\nA --> B\n')
        self.assertNotEqual(code, 0)
        self.assertIn(':2:', err)
        self.assertIsNone(out)


if __name__ == '__main__':
    unittest.main()
