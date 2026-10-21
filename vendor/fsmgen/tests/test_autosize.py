"""Content-driven state sizes must handle wide glyphs and multiline actions."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsmast import Parser
from layout import layout_fsm
from drawio_out import to_xml


def generate(source):
    fsm = Parser().parse(source)
    layout = layout_fsm(fsm)
    cells = {c.get('id'): c for c in to_xml(fsm, layout).iter('mxCell')}
    return layout, cells


class AutoSizeTest(unittest.TestCase):
    def test_wide_state_title_grows_beyond_the_preferred_width(self):
        title = 'W' * 80
        layout, cells = generate('state A : ' + title + '\n')
        self.assertGreater(layout.nodes['A'].width, 800)
        self.assertIn(title, cells['fsm_A'].get('value'))

    def test_unbreakable_action_identifier_is_not_clipped_at_420(self):
        action = 'VeryLongFunction' * 12 + '()'
        layout, cells = generate('state A {\n  entry: ' + action + '\n}\n')
        self.assertGreater(layout.nodes['A'].width, 420)
        self.assertIn(action, cells['fsm_A'].get('value'))

    def test_long_action_wraps_and_grows_vertically(self):
        action = ' '.join(['evaluate measured alarm pulse counts'] * 12)
        layout, cells = generate('state A {\n  on Tick: ' + action + '\n}\n')
        self.assertLessEqual(layout.nodes['A'].width, 420)
        self.assertGreater(layout.nodes['A'].height, 100)
        self.assertGreater(cells['fsm_A'].get('value').count('<br>'), 3)

    def test_explicit_title_and_action_line_breaks_are_rendered(self):
        _, cells = generate('state A : Alarm\\nEvaluation {\n  entry: first()\\nsecond()\n}\n')
        value = cells['fsm_A'].get('value')
        self.assertIn('Alarm<br>Evaluation', value)
        self.assertIn('first()<br>second()', value)
        self.assertNotIn('\\n', value)


if __name__ == '__main__':
    unittest.main()
