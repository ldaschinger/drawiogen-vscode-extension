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

CONTAINERS = ('package', 'component')
DEFAULT_STEREOTYPE = {'interface': 'interface', 'enum': 'enumeration'}


class ClsError(DiagramError):
    pass


@dataclass
class Member:
    visibility: str     # '+', '-', '#', '~' or '' for enum literals
    text: str
    is_method: bool


@dataclass
class Element:
    id: str
    kind: str           # package | component | class | interface | enum
    label: str
    stereotype: Optional[str]
    line_number: int
    members: List[Member] = field(default_factory=list)
    children: List['Element'] = field(default_factory=list)
    parent: Optional[str] = None
    has_body: bool = False      # written with { } (members shown as class compartments)
    top_row: Optional['LayoutGroup'] = None

    @property
    def is_container(self) -> bool:
        return self.kind in CONTAINERS and bool(self.children)


@dataclass
class Relation:
    source: str
    target: str
    arrow: str
    src_mult: Optional[str]
    tgt_mult: Optional[str]
    label: str
    line_number: int


@dataclass
class LayoutGroup:
    names: List[str]
    line_number: int


@dataclass
class Cls:
    title: str = ''
    direction: str = 'TB'
    elements: Dict[str, Element] = field(default_factory=dict)   # flat, all nesting levels
    roots: List[Element] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)
    arrangement: Optional[str] = None  # top-level siblings in declaration order; None = automatic
    same_size: List[LayoutGroup] = field(default_factory=list)
    horizontal: List[LayoutGroup] = field(default_factory=list)
    notes: List[Note] = field(default_factory=list)


class Parser:
    def __init__(self):
        with open(SCRIPT_DIR / 'syntax.lark', 'r') as f:
            grammar = f.read()

        self.lark = Lark(grammar, start='start', propagate_positions=True)

    def parse(self, text: str) -> Cls:
        text = text.replace('\r', '')
        if not text.endswith('\n'):
            text += '\n'

        parsed = self.lark.parse(text)
        statements = ClsTransformer().transform(parsed)
        return build_cls(statements)


def pick(items, tag: str):
    for item in items:
        if isinstance(item, tuple) and item[0] == tag:
            return item[1]
    return None


class ClsTransformer(Transformer):
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
    def arrangement(items):
        return {'kind': 'arrangement', 'value': str(items[0])}

    @staticmethod
    def same_size(items):
        return {'kind': 'same_size', 'names': [str(i) for i in items]}

    @staticmethod
    def align_horizontal(items):
        return {'kind': 'horizontal', 'names': [str(i) for i in items]}

    @staticmethod
    def top_row(items):
        return {'kind': 'top_row', 'names': [str(i) for i in items]}

    @staticmethod
    def label(items):
        return ('label', str(items[0]).strip())

    @staticmethod
    def stereotype(items):
        return ('stereotype', str(items[0]).strip()[2:-2].strip())

    @staticmethod
    def src_mult(items):
        return ('src', str(items[0])[1:-1])

    @staticmethod
    def tgt_mult(items):
        return ('tgt', str(items[0])[1:-1])

    @staticmethod
    def container(items):
        return {'kind': 'element', 'type': str(items[0]), 'name': str(items[1]),
                'label': pick(items, 'label'), 'stereotype': None, 'body': 'children',
                'children': items[-1] if isinstance(items[-1], list) else []}

    @staticmethod
    def member_line(items):
        return str(items[0])

    @staticmethod
    def block(items):
        return {'kind': 'element', 'type': str(items[0]), 'name': str(items[1]),
                'label': pick(items, 'label'), 'stereotype': pick(items, 'stereotype'),
                'body': 'members', 'members': [i for i in items if isinstance(i, str)][2:]}

    @staticmethod
    def leaf(items):
        return {'kind': 'element', 'type': str(items[0]), 'name': str(items[1]),
                'label': pick(items, 'label'), 'stereotype': pick(items, 'stereotype'),
                'body': 'none'}

    @staticmethod
    def relation(items):
        names = [i for i in items if not isinstance(i, tuple) and i.type == 'NAME']
        arrow = [i for i in items if not isinstance(i, tuple) and i.type == 'ARROW'][0]
        text = [i for i in items if not isinstance(i, tuple) and i.type == 'TEXT']
        return {'kind': 'relation', 'source': str(names[0]), 'target': str(names[1]),
                'arrow': str(arrow), 'src_mult': pick(items, 'src'), 'tgt_mult': pick(items, 'tgt'),
                'label': str(text[0]).strip() if text else ''}


def parse_member(text: str, line: int, kind: str) -> Member:
    if kind == 'enum':
        if text[0] in '+-#~':
            raise ClsError('Enum entries are plain literal names, without a visibility marker', line)
        return Member('', text.strip(), False)

    if text[0] not in '+-#~':
        raise ClsError('Members of a class or interface start with + - # or ~', line)
    body = text[1:].strip()
    return Member(text[0], body, '(' in body)


def build_cls(statements: List[dict]) -> Cls:
    cls = Cls()

    def add_elements(nodes: List[dict], parent: Optional[Element]) -> List[Element]:
        elements = []
        for node in nodes:
            kind, line = node['kind'], node['line']

            if kind == 'note':
                cls.notes.append(make_note(node))
            elif kind == 'title':
                cls.title = node['text']
            elif kind == 'direction':
                cls.direction = node['value']
            elif kind == 'arrangement':
                if parent is not None:
                    raise ClsError('arrange is only supported at the top level', line)
                cls.arrangement = node['value']
            elif kind in ('same_size', 'horizontal'):
                if parent is not None:
                    raise ClsError('Layout groups are only supported at the top level', line)
                getattr(cls, kind).append(LayoutGroup(node['names'], line))
            elif kind == 'top_row':
                if parent is None:
                    raise ClsError('top-row belongs inside a package or component container', line)
                if parent.top_row is not None:
                    raise ClsError('A container may have only one top-row directive', line)
                parent.top_row = LayoutGroup(node['names'], line)
            elif kind == 'relation':
                cls.relations.append(Relation(node['source'], node['target'], node['arrow'],
                                              node['src_mult'], node['tgt_mult'], node['label'], line))
            else:
                element = make_element(node, line, parent)
                elements.append(element)
        return elements

    def make_element(node: dict, line: int, parent: Optional[Element]) -> Element:
        name, type_ = node['name'], node['type']
        if name in cls.elements:
            raise ClsError(f'Duplicate element "{name}"', line)
        if node['body'] == 'children' and type_ not in CONTAINERS:
            raise ClsError(f'"{type_}" cannot contain other elements', line)
        if type_ == 'package' and node['body'] != 'children':
            raise ClsError('A package needs a body with { }', line)

        stereotype = node['stereotype'] or DEFAULT_STEREOTYPE.get(type_)
        element = Element(name, type_, node['label'] or name, stereotype, line,
                          parent=parent.id if parent else None,
                          has_body=node['body'] == 'members')
        cls.elements[name] = element

        if node['body'] == 'children':
            if not node['children']:
                raise ClsError(f'{type_} "{name}" is empty', line)
            element.children = add_elements(node['children'], element)
        elif node['body'] == 'members':
            element.members = [parse_member(m, line, type_) for m in node['members']]

        return element

    cls.roots = add_elements(statements, None)
    validate(cls)
    return cls


def validate(cls: Cls) -> None:
    for note in cls.notes:
        if note.target not in cls.elements:
            raise ClsError(f'Unknown note target "{note.target}"', note.line_number)

    for element in cls.elements.values():
        group = element.top_row
        if group is None:
            continue
        if cls.direction != 'TB':
            raise ClsError('top-row requires direction: TB', group.line_number)
        if len(set(group.names)) != len(group.names):
            raise ClsError('top-row must name distinct elements', group.line_number)
        for name in group.names:
            child = cls.elements.get(name)
            if child is None:
                raise ClsError(f'Unknown element "{name}"', group.line_number)
            if child.parent != element.id or child.is_container:
                raise ClsError('top-row names direct leaf children of its container',
                               group.line_number)

    for group in cls.same_size + cls.horizontal:
        if len(set(group.names)) != len(group.names):
            raise ClsError('A layout group must name distinct elements', group.line_number)
        for name in group.names:
            if name not in cls.elements:
                raise ClsError(f'Unknown element "{name}"', group.line_number)

    for group in cls.same_size:
        if cls.arrangement is None:
            raise ClsError('same-size requires arrange: LR or arrange: TB', group.line_number)
        if any(cls.elements[n].parent is not None or not cls.elements[n].is_container
               for n in group.names):
            raise ClsError('same-size names top-level package or component containers',
                           group.line_number)

    for group in cls.horizontal:
        if cls.arrangement != 'LR':
            raise ClsError('align-horizontal requires arrange: LR', group.line_number)
        if any(cls.elements[n].parent is None or cls.elements[n].is_container
               for n in group.names):
            raise ClsError('align-horizontal names leaf elements inside separate top-level blocks',
                           group.line_number)
        roots = [top_level_element(cls, n).id for n in group.names]
        if len(set(roots)) != len(roots):
            raise ClsError('align-horizontal elements must be in separate top-level blocks',
                           group.line_number)

    for relation in cls.relations:
        for name in (relation.source, relation.target):
            element = cls.elements.get(name)
            if element is None:
                raise ClsError(f'Unknown element "{name}"', relation.line_number)
            if element.is_container:
                raise ClsError(f'"{name}" is a container; relations connect leaf elements only',
                               relation.line_number)


def top_level_element(cls: Cls, name: str) -> Element:
    element = cls.elements[name]
    while element.parent is not None:
        element = cls.elements[element.parent]
    return element
