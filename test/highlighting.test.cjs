const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { before, test } = require('node:test');
const { Registry, parseRawGrammar } = require('vscode-textmate');
const { loadWASM, OnigScanner, OnigString } = require('vscode-oniguruma');

const root = path.resolve(__dirname, '..');
let registry;
before(async () => {
    const wasm = fs.readFileSync(require.resolve('vscode-oniguruma/release/onig.wasm'));
    await loadWASM(wasm.buffer.slice(wasm.byteOffset, wasm.byteOffset + wasm.byteLength));
    registry = new Registry({
        onigLib: Promise.resolve({ createOnigScanner: p => new OnigScanner(p), createOnigString: s => new OnigString(s) }),
        loadGrammar: async scope => {
            const language = scope.split('.').at(-1);
            const filename = path.join(root, 'syntaxes', `${language}.tmLanguage.json`);
            return parseRawGrammar(fs.readFileSync(filename, 'utf8'), filename);
        },
    });
});

async function tokenize(language, lines) {
    const grammar = await registry.loadGrammar(`source.${language}`);
    let state = null;
    return lines.map(line => {
        const result = grammar.tokenizeLine(line, state);
        state = result.ruleStack;
        return result.tokens.map(token => ({ text: line.slice(token.startIndex, token.endIndex), scopes: token.scopes }));
    });
}
function has(tokens, text, scope) {
    assert.ok(tokens.some(t => t.text.trim() === text && t.scopes.includes(scope)),
        `missing ${scope} for ${text}: ${JSON.stringify(tokens)}`);
}

for (const language of ['cls', 'fsm']) {
    test(`${language}: manifest registers highlighting and editor configuration`, () => {
        const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json')));
        const grammar = manifest.contributes.grammars.find(g => g.language === language);
        assert.ok(fs.existsSync(path.join(root, grammar.path)));
        const definition = manifest.contributes.languages.find(l => l.id === language);
        const config = JSON.parse(fs.readFileSync(path.join(root, definition.configuration)));
        assert.equal(config.comments.lineComment, '//');
        assert.ok(config.brackets.some(pair => pair.join('') === '{}'));
    });
    test(`${language}: comments and notes keep their text intact`, async () => {
        const [comment, note, colon] = await tokenize(language, [
            '  // comment', 'note on Target width 180: URL https://example.test/{id}',
            'note on Target: next note',
        ]);
        has(comment, '// comment', `comment.line.double-slash.${language}`);
        has(note, 'note', `keyword.other.${language}`);
        has(note, 'Target', `entity.name.type.${language}`);
        has(note, '180', `constant.numeric.${language}`);
        has(note, 'URL https://example.test/{id}', `string.unquoted.note.${language}`);
        has(colon, 'next note', `string.unquoted.note.${language}`);
    });
}

test('cls: declarations, stereotypes, members, multiplicities, arrows and enum literals', async () => {
    const [declaration, method, relation, , literal, , afterEnum] = await tokenize('cls', [
        'class Service : My service <<object>> {', '  + Run(): bool',
        'Service "1" ..|> "0..*" Interface : implements',
        'enum Mode {', '  Idle = 1', '}', 'component Other',
    ]);
    has(declaration, 'class', 'keyword.declaration.cls');
    has(declaration, 'Service', 'entity.name.type.cls');
    has(declaration, '<<object>>', 'storage.type.stereotype.cls');
    has(method, '+', 'storage.modifier.cls');
    has(method, 'Run', 'entity.name.function.cls');
    has(relation, '..|>', 'keyword.operator.arrow.cls');
    has(relation, '"0..*"', 'string.quoted.double.cls');
    has(literal, 'Idle', 'constant.other.enum.cls');
    has(afterEnum, 'component', 'keyword.declaration.cls');
});

test('fsm: states, choices, actions, events and transitions', async () => {
    const [state, choice, entry, event, edge] = await tokenize('fsm', [
        'state Idle : Waiting {', 'choice Ready: Ready?', '  entry: Start()',
        '  on Tick: Count()', 'Idle -> Ready: Go [ok] / Run()',
    ]);
    has(state, 'Idle', 'entity.name.type.fsm');
    has(choice, 'choice', 'keyword.declaration.fsm');
    has(entry, 'entry', 'keyword.control.fsm');
    has(event, 'Tick', 'entity.name.function.fsm');
    has(edge, '->', 'keyword.operator.arrow.fsm');
    has(edge, 'Go [ok] / Run()', 'string.unquoted.label.fsm');
});
