import * as vscode from 'vscode';

type Reference = { name: string; line: number; column: number; note: boolean };

/** Lightweight editor feedback; the Python parser remains authoritative. */
export function runDiagramHints(doc: vscode.TextDocument, language: 'cls' | 'fsm'): vscode.Diagnostic[] {
    const hints: vscode.Diagnostic[] = [];
    const declarations = new Map<string, { line: number; column: number }>();
    const references: Reference[] = [];
    const transitions: { source: string; target: string }[] = [];
    const blocks: { name: string; kind: string; line: number; column: number }[] = [];
    let duplicate = false;

    function hint(line: number, column: number, name: string, message: string) {
        const diagnostic = new vscode.Diagnostic(
            new vscode.Range(line, column, line, column + name.length),
            message, vscode.DiagnosticSeverity.Hint);
        diagnostic.source = 'drawiogen';
        hints.push(diagnostic);
    }

    function reference(name: string, line: number, column: number, note = false) {
        references.push({ name, line, column, note });
    }

    for (let line = 0; line < doc.lineCount; line++) {
        const raw = doc.lineAt(line).text;
        const text = raw.trim();
        if (!text || text.startsWith('//')) { continue; }
        if (text === '}') {
            if (blocks.length) { blocks.pop(); }
            else { hint(line, raw.indexOf('}'), '}', 'Unexpected "}" — no open block'); }
            continue;
        }
        // Actions/member text can contain arbitrary braces and diagram-like words.
        const body = blocks.at(-1);
        if (body && (language === 'fsm' || !['package', 'component'].includes(body.kind))) { continue; }

        const declaration = text.match(language === 'fsm'
            ? /^(state|choice)\s+([A-Za-z0-9_]+)(?=\s|:|\{|$)/
            : /^(package|component|class|interface|enum)\s+([A-Za-z0-9_]+)(?=\s|:|\{|$)/);
        if (declaration) {
            const [, kind, name] = declaration;
            const column = raw.indexOf(name, raw.indexOf(kind) + kind.length);
            if (declarations.has(name)) {
                duplicate = true;
                hint(line, column, name, `Duplicate ${language === 'fsm' ? 'state or choice' : 'element'} "${name}"`);
            } else { declarations.set(name, { line, column }); }
            if (language === 'fsm' && ['initial', 'final'].includes(name)) {
                hint(line, column, name, `"${name}" is reserved for the pseudostate`);
            }
            if (text.endsWith('{')) { blocks.push({ name, kind, line, column }); }
            continue;
        }
        const note = text.match(/^note\s+on\s+([A-Za-z0-9_]+)(?=\s|:|\{|$)/);
        if (note) {
            reference(note[1], line, raw.indexOf(note[1], raw.indexOf('on') + 2), true);
            continue;
        }
        const edge = text.match(language === 'fsm'
            ? /^([A-Za-z0-9_]+)\s+->\s+([A-Za-z0-9_]+)(?=\s|:|\{|$)/d
            : /^([A-Za-z0-9_]+)(?:\s+"[^"\n]*")?\s+(--\|>|\.\.\|>|\*--|o--|-->|\.\.>|--|\.\.)\s+(?:"[^"\n]*"\s+)?([A-Za-z0-9_]+)(?=\s|:|\{|$)/d);
        if (edge) {
            const source = edge[1];
            const target = edge[language === 'fsm' ? 2 : 3];
            const indentation = raw.indexOf(text);
            const sourceColumn = indentation + edge.indices![1][0];
            const targetColumn = indentation + edge.indices![language === 'fsm' ? 2 : 3][0];
            reference(source, line, sourceColumn);
            reference(target, line, targetColumn);
            transitions.push({ source, target });
        }
    }

    for (const block of blocks) {
        hint(block.line, block.column, block.name, `Unclosed ${block.kind} "${block.name}" — missing "}"`);
    }
    const pseudostates = new Set(language === 'fsm' ? ['initial', 'final'] : []);
    const drawn = new Set(transitions.flatMap(t => [t.source, t.target]));
    let unknown = false;
    for (const ref of references) {
        if (declarations.has(ref.name)) { continue; }
        if (pseudostates.has(ref.name) && (!ref.note || drawn.has(ref.name))) { continue; }
        unknown = true;
        hint(ref.line, ref.column, ref.name,
            `Unknown ${ref.note ? 'note target' : language === 'fsm' ? 'state or choice' : 'element'} "${ref.name}"`);
    }
    if (language === 'fsm' && !duplicate && !unknown && blocks.length === 0
        && transitions.filter(t => t.source === 'initial').length === 1) {
        const adjacent = new Map<string, string[]>();
        for (const edge of transitions) {
            const neighbors = adjacent.get(edge.source) ?? [];
            neighbors.push(edge.target);
            adjacent.set(edge.source, neighbors);
        }
        const reachable = new Set(['initial']);
        const pending = ['initial'];
        while (pending.length) {
            for (const target of adjacent.get(pending.pop()!) ?? []) {
                if (!reachable.has(target)) { reachable.add(target); pending.push(target); }
            }
        }
        for (const [name, position] of declarations) {
            if (!reachable.has(name)) {
                hint(position.line, position.column, name, `"${name}" is unreachable from "initial"`);
            }
        }
    }
    return hints;
}
