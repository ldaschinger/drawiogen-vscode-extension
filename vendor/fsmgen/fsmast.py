import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from lark import Lark, Transformer

from diagramerror import DiagramError
from annotations import Note, make_note, note_statement

SCRIPT_DIR = Path(__file__).parent

INITIAL = 'initial'
FINAL = 'final'


class FsmError(DiagramError):
    pass


@dataclass
class State:
    name: str
    label: str
    line_number: int
    entry: List[str] = field(default_factory=list)
    exit: List[str] = field(default_factory=list)
    internal: List[tuple] = field(default_factory=list)  # (event, action)


@dataclass
class Choice:
    name: str
    label: str
    line_number: int


@dataclass
class Transition:
    source: str
    target: str
    label: str
    line_number: int


@dataclass
class Fsm:
    title: str = ''
    direction: str = 'TB'
    states: Dict[str, State] = field(default_factory=dict)
    choices: Dict[str, Choice] = field(default_factory=dict)
    transitions: List[Transition] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)
    transition_spacing: float = 50.4  # px between ranks, in addition to label space
    transition_label_width: Optional[float] = None  # px; None retains 32-character wrapping


class Parser:
    def __init__(self):
        with open(SCRIPT_DIR / 'syntax.lark', 'r') as f:
            grammar = f.read()

        self.lark = Lark(grammar, start='start', propagate_positions=True)

    def parse(self, text: str) -> Fsm:
        text = text.replace('\r', '')
        if not text.endswith('\n'):
            text += '\n'

        parsed = self.lark.parse(text)
        statements = FsmTransformer().transform(parsed)
        return build_fsm(statements)


class FsmTransformer(Transformer):
    @staticmethod
    def start(items):
        return items[0]

    @staticmethod
    def statement_list(items):
        result = []
        for item in items:
            node = item.children[0]
            node['line'] = item.meta.line
            result.append(node)
        return result

    note = staticmethod(note_statement)

    @staticmethod
    def title(items):
        return {'kind': 'title', 'text': str(items[0])}

    @staticmethod
    def direction(items):
        return {'kind': 'direction', 'value': str(items[0])}

    @staticmethod
    def transition_spacing(items):
        return {'kind': 'transition_spacing', 'value': float(items[0])}

    @staticmethod
    def transition_label_width(items):
        return {'kind': 'transition_label_width', 'value': float(items[0])}

    @staticmethod
    def state_label(items):
        return ('label', str(items[0]).strip())

    @staticmethod
    def choice(items):
        return {'kind': 'choice', 'name': str(items[0]), 'label': label_of(items)}

    @staticmethod
    def state_leaf(items):
        return {'kind': 'state', 'name': str(items[0]), 'label': label_of(items), 'body': []}

    @staticmethod
    def state_block(items):
        body = [i for i in items[1:] if i[0] != 'label']
        return {'kind': 'state', 'name': str(items[0]), 'label': label_of(items), 'body': body}

    @staticmethod
    def state_item(items):
        return items[0]

    @staticmethod
    def entry(items):
        return ('entry', str(items[0]))

    @staticmethod
    def exit(items):
        return ('exit', str(items[0]))

    @staticmethod
    def internal(items):
        return ('on', str(items[0]), str(items[1]))

    @staticmethod
    def transition(items):
        return {'kind': 'transition', 'source': str(items[0]), 'target': str(items[1]),
                'label': str(items[2]) if len(items) > 2 else ''}


def label_of(items) -> Optional[str]:
    for item in items[1:]:
        if isinstance(item, tuple) and item[0] == 'label':
            return item[1]
    return None


def build_fsm(statements: List[dict]) -> Fsm:
    fsm = Fsm()
    reserved = {INITIAL, FINAL}

    def check_unique(name: str, line: int):
        if name in reserved:
            raise FsmError(f'"{name}" is reserved for the pseudostate', line)
        if name in fsm.states or name in fsm.choices:
            raise FsmError(f'Duplicate state or choice "{name}"', line)

    for node in statements:
        kind = node['kind']
        line = node['line']

        if kind == 'note':
            fsm.notes.append(make_note(node))
        elif kind == 'title':
            fsm.title = node['text']
        elif kind == 'direction':
            fsm.direction = node['value']
        elif kind in ('transition_spacing', 'transition_label_width'):
            if node['value'] <= 0:
                raise FsmError(kind.replace('_', '-') + ' must be greater than zero', line)
            setattr(fsm, kind, node['value'])
        elif kind == 'choice':
            check_unique(node['name'], line)
            fsm.choices[node['name']] = Choice(node['name'], node['label'] or node['name'], line)
        elif kind == 'state':
            check_unique(node['name'], line)
            state = State(node['name'], node['label'] or node['name'], line)
            for item in node['body']:
                if item[0] == 'entry':
                    state.entry.append(item[1])
                elif item[0] == 'exit':
                    state.exit.append(item[1])
                else:
                    state.internal.append((item[1], item[2]))
            fsm.states[node['name']] = state
        elif kind == 'transition':
            fsm.transitions.append(Transition(node['source'], node['target'], node['label'], line))

    validate(fsm)
    return fsm


def validate(fsm: Fsm) -> None:
    known = set(fsm.states) | set(fsm.choices) | {INITIAL, FINAL}
    initial_count = 0

    for t in fsm.transitions:
        for name in (t.source, t.target):
            if name not in known:
                raise FsmError(f'Unknown state "{name}"', t.line_number)
        if t.source == FINAL:
            raise FsmError('Transition cannot leave the final state', t.line_number)
        if t.target == INITIAL:
            raise FsmError('Transition cannot enter the initial state', t.line_number)
        if t.source == INITIAL:
            initial_count += 1
            if initial_count > 1:
                raise FsmError('Only one transition may leave "initial"', t.line_number)

    drawn = set(fsm.states) | set(fsm.choices)
    drawn |= {n for t in fsm.transitions for n in (t.source, t.target)}
    for note in fsm.notes:
        if note.target not in drawn:
            raise FsmError(f'Unknown note target "{note.target}"', note.line_number)
