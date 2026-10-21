import math
import os
import sys
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

from fsmrouting import EdgeRoute, route_graph, EDGE_FONT_SIZE
from textmetrics import measure_texts, text_width, wrap_measured

from fsmast import Fsm, INITIAL, FINAL

BODY_FONT_SIZE = 10
TITLE_FONT_SIZE = 12
LINE_HEIGHT = 13
INDENT = '    '          # action lines are indented below their Entry:/Exit: heading
STATE_MIN_WIDTH = 160
STATE_MAX_WIDTH = 420
STATE_PADDING_X = 24
STATE_PADDING_Y = 24
TITLE_HEIGHT = 30
CHOICE_SIZE = 40
PSEUDO_SIZE = 30
EDGE_LABEL_WRAP = 32    # characters per line of an edge label


@dataclass
class Node:
    id: str
    kind: str           # 'state' | 'choice' | 'initial' | 'final'
    width: float
    height: float
    x: float = 0
    y: float = 0


@dataclass
class Layout:
    nodes: Dict[str, Node]
    width: float
    height: float
    routes: List[EdgeRoute]
    edge_labels: List[List[str]]


def state_lines(state) -> List[str]:
    """Display lines of a state body: Entry, Exit and event handlers, separated by a blank line."""
    groups = []
    if state.entry:
        groups.append(['Entry:'] + [INDENT + text for text in state.entry])
    if state.exit:
        groups.append(['Exit:'] + [INDENT + text for text in state.exit])
    if state.internal:
        groups.append([f'Event {event}: {action}' for event, action in state.internal])

    lines: List[str] = []
    for group in groups:
        if lines:
            lines.append('')
        lines.extend(group)
    return lines


def split_text(text: str) -> List[str]:
    return text.replace('\\n', '\n').split('\n')


def state_text_requests(state):
    requests = [(line, TITLE_FONT_SIZE, True) for line in split_text(state.label)]
    requests.append((' ', BODY_FONT_SIZE, False))
    for line in state_lines(state):
        for part in split_text(line):
            requests.append((part, BODY_FONT_SIZE, False))
            requests.extend((word, BODY_FONT_SIZE, False) for word in part.split())
    return requests


def wrap_body_line(line: str, available_width: float) -> List[str]:
    if text_width(line, BODY_FONT_SIZE) <= available_width:
        return [line]
    indent = line[:len(line) - len(line.lstrip(' '))]
    continuation = indent or (INDENT if line.startswith('Event ') else '')
    result = []
    current = indent
    for word in line.strip().split():
        candidate = current + ('' if not current.strip() else ' ') + word
        if current.strip() and text_width(candidate, BODY_FONT_SIZE) > available_width:
            result.append(current)
            current = continuation + word
        else:
            current = candidate
    return result + [current]


def state_content(state):
    measure_texts(state_text_requests(state))
    title_lines = split_text(state.label)
    raw_lines = [part for line in state_lines(state) for part in split_text(line)]
    title_width = max(text_width(line, TITLE_FONT_SIZE, True) for line in title_lines)
    longest_body = max([text_width(line, BODY_FONT_SIZE) for line in raw_lines] + [0])
    # 420 px is a preferred wrapping width, not a clipping limit. Long titles
    # and unbreakable identifiers can grow beyond it without losing text.
    longest_word = max([text_width(word, BODY_FONT_SIZE) for line in raw_lines
                        for word in line.split()] + [0])
    indent_width = len(INDENT) * text_width(' ', BODY_FONT_SIZE)
    width = math.ceil(max(STATE_MIN_WIDTH, title_width + STATE_PADDING_X,
                          min(STATE_MAX_WIDTH, longest_body + STATE_PADDING_X),
                          longest_word + indent_width + STATE_PADDING_X))
    lines = [part for line in raw_lines for part in wrap_body_line(line, width - STATE_PADDING_X)]
    height = TITLE_HEIGHT + (len(title_lines) - 1) * 16 + len(lines) * LINE_HEIGHT + STATE_PADDING_Y
    return width, height, lines


def display_state_lines(state) -> List[str]:
    return state_content(state)[2]


def size_of_state(state) -> Tuple[float, float]:
    width, height, _ = state_content(state)
    return width, height


def build_nodes(fsm: Fsm) -> Dict[str, Node]:
    nodes: Dict[str, Node] = {}
    measure_texts(request for state in fsm.states.values() for request in state_text_requests(state))

    for state in fsm.states.values():
        w, h = size_of_state(state)
        nodes[state.name] = Node(state.name, 'state', w, h)

    for choice in fsm.choices.values():
        nodes[choice.name] = Node(choice.name, 'choice', CHOICE_SIZE, CHOICE_SIZE)

    used = {t.source for t in fsm.transitions} | {t.target for t in fsm.transitions}
    if INITIAL in used:
        nodes[INITIAL] = Node(INITIAL, 'initial', PSEUDO_SIZE, PSEUDO_SIZE)
    if FINAL in used:
        nodes[FINAL] = Node(FINAL, 'final', PSEUDO_SIZE, PSEUDO_SIZE)

    return nodes


def wrap_edge_label(label: str, width: float = None) -> List[str]:
    lines = []
    for part in split_text(label):
        lines.extend(wrap_measured(part, width, EDGE_FONT_SIZE) if width is not None
                     else textwrap.wrap(part, EDGE_LABEL_WRAP) or [''])
    return lines


def layout_fsm(fsm: Fsm) -> Layout:
    nodes = build_nodes(fsm)
    labels = [wrap_edge_label(t.label, fsm.transition_label_width) for t in fsm.transitions]
    width, height, routes = route_graph(nodes, fsm.transitions, labels, fsm.direction,
                                      spacing=fsm.transition_spacing)
    return Layout(nodes, width, height, routes, labels)
