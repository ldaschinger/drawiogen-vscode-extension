"""Long transition labels can request more line width and state separation."""
import html
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsmast import Parser, FsmError
from layout import layout_fsm, wrap_edge_label
from drawio_out import to_xml
from textmetrics import measure_texts, text_width
from fsmrouting import EDGE_FONT_SIZE


class TransitionFormattingTest(unittest.TestCase):
    def test_settings_parse_pixel_values(self):
        fsm = Parser().parse('transition-spacing: 110.5\ntransition-label-width: 300\nstate A\n')
        self.assertEqual(fsm.transition_spacing, 110.5)
        self.assertEqual(fsm.transition_label_width, 300)

    def test_nonpositive_settings_report_their_source_line(self):
        for setting in ('transition-spacing', 'transition-label-width'):
            for value in (0, -10):
                with self.subTest(setting=setting, value=value):
                    with self.assertRaises(FsmError) as error:
                        Parser().parse(f'state A\n{setting}: {value}\n')
                    self.assertEqual(error.exception.line, 2)

    def test_spacing_makes_arrows_longer_in_both_directions(self):
        for direction in ('TB', 'LR'):
            with self.subTest(direction=direction):
                source = f'direction: {direction}\nstate A\nstate B\nA -> B : advance\n'
                default = layout_fsm(Parser().parse(source))
                larger = layout_fsm(Parser().parse('transition-spacing: 160\n' + source))
                axis = 'y' if direction == 'TB' else 'x'
                default_gap = getattr(default.nodes['B'], axis) - getattr(default.nodes['A'], axis)
                larger_gap = getattr(larger.nodes['B'], axis) - getattr(larger.nodes['A'], axis)
                self.assertGreater(larger_gap, default_gap + 80)

    def test_wider_guard_label_wraps_less_without_losing_text(self):
        text = 'evSummaryAvailable [isLatestSummary == true]/'
        narrow = wrap_edge_label(text, 100)
        wide = wrap_edge_label(text, 300)
        self.assertLess(len(wide), len(narrow))
        self.assertEqual(''.join(wide).replace(' ', ''), text.replace(' ', ''))

    def test_unbroken_identifiers_fit_the_requested_line_width(self):
        text = 'W' * 60
        lines = wrap_edge_label(text, 40)
        self.assertEqual(''.join(lines), text)
        measure_texts((line, EDGE_FONT_SIZE, False) for line in lines)
        for line in lines:
            self.assertLessEqual(text_width(line, EDGE_FONT_SIZE), 40)

    def test_explicit_label_line_breaks_remain_and_export_matches_layout(self):
        source = ('transition-label-width: 300\nstate A\nstate B\n'
                  'A -> B : evSummaryAvailable [isLatestSummary == true]/\\nevaluateStallingSumary\n')
        fsm = Parser().parse(source)
        layout = layout_fsm(fsm)
        self.assertEqual(len(layout.edge_labels[0]), 2)
        cells = {c.get('id'): c for c in to_xml(fsm, layout).iter('mxCell')}
        expected = '<br>'.join(html.escape(line) for line in layout.edge_labels[0])
        self.assertEqual(cells['fsm_edge_0'].get('value'), expected)


if __name__ == '__main__':
    unittest.main()
