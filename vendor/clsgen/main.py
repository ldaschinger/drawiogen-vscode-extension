import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

from diagramerror import DiagramError
from clsast import Parser
from layout import layout_cls
from drawio_out import to_xml, xml_pretty


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--output', type=str, help='Output file')
    parser.add_argument('input', type=str, help='Input file')
    args = parser.parse_args()

    input_path = args.input
    output_path = args.output or change_ext(input_path, '.drawio')

    with open(input_path, 'r') as f:
        source = f.read()

    try:
        cls = Parser().parse(source)
        layout = layout_cls(cls)
        output = xml_pretty(to_xml(cls, layout))
    except DiagramError as e:
        sys.exit(f'{input_path}:{e.line}: {e}')

    with open(output_path, 'w') as f:
        f.write(output)


def change_ext(path, new_ext):
    return os.path.splitext(path)[0] + new_ext


if __name__ == '__main__':
    main()
