// Exercise the extension's event handlers with real Python parsers/generators.
// A small VS Code host stub records diagnostics and split-view requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const Module = require('node:module');
const os = require('node:os');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { after, before, test } = require('node:test');

const extensionPath = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'drawiogen-integration-'));
const handlers = {};
const commands = new Map();
const collections = new Map();
const previews = [];
const messages = [];
const subscriptions = [];
const documents = [];
let nextFile = 0;

const disposable = () => ({ dispose() {} });
const uri = fileName => ({ scheme: 'file', fsPath: fileName, toString: () => `file://${fileName}` });
const vscode = {
    StatusBarAlignment: { Left: 1 },
    DiagnosticSeverity: { Error: 0, Hint: 3 },
    ViewColumn: { Beside: -2 },
    Uri: { file: uri },
    Range: class {
        constructor(line, character, endLine, endCharacter) {
            this.start = { line, character };
            this.end = { line: endLine, character: endCharacter };
        }
    },
    Diagnostic: class {
        constructor(range, message, severity) { Object.assign(this, { range, message, severity }); }
    },
    TabInputCustom: class {},
    TabInputText: class {},
    workspace: {
        textDocuments: documents,
        workspaceFolders: [{ uri: uri(temporary) }],
        onDidOpenTextDocument: handler => { handlers.open = handler; return disposable(); },
        onDidChangeTextDocument: handler => { handlers.change = handler; return disposable(); },
        onDidCloseTextDocument: handler => { handlers.close = handler; return disposable(); },
        onDidSaveTextDocument: handler => { handlers.save = handler; return disposable(); },
    },
    languages: {
        createDiagnosticCollection(name) {
            const entries = new Map();
            collections.set(name, entries);
            return {
                set: (uri, diagnostics) => entries.set(uri.toString(), diagnostics),
                delete: uri => entries.delete(uri.toString()),
                dispose() { entries.clear(); },
            };
        },
    },
    window: {
        createStatusBarItem: () => ({ show() {}, hide() {}, dispose() {} }),
        showErrorMessage: message => messages.push(message),
        tabGroups: { all: [] },
        activeTextEditor: undefined,
    },
    commands: {
        registerCommand(name, handler) { commands.set(name, handler); return disposable(); },
        async executeCommand(name, uri, options) { previews.push({ name, uri, options }); },
    },
};

before(() => {
    function loadExtensionModule(filename) {
        const loaded = new Module(filename, module);
        loaded.filename = filename;
        loaded.paths = Module._nodeModulePaths(path.dirname(filename));
        const originalRequire = loaded.require.bind(loaded);
        loaded.require = name => name === 'vscode' ? vscode
            : name.startsWith('./') ? loadExtensionModule(path.resolve(path.dirname(filename), name + '.js'))
            : originalRequire(name);
        loaded._compile(fs.readFileSync(filename, 'utf8'), filename);
        return loaded.exports;
    }
    loadExtensionModule(path.join(extensionPath, 'out/extension.js')).activate({ extensionPath, subscriptions });
});

after(() => {
    for (const doc of documents) {
        doc.isClosed = true;
        handlers.close(doc);
    }
    subscriptions.forEach(subscription => subscription.dispose());
    fs.rmSync(temporary, { recursive: true, force: true });
});

function open(language, text) {
    const fileName = path.join(temporary, `diagram-${++nextFile}.${language}`);
    fs.writeFileSync(fileName, text);
    const doc = {
        fileName, uri: uri(fileName), languageId: language, version: 1, isClosed: false, text,
        getText() { return this.text; },
        get lineCount() { return this.text.split('\n').length; },
        lineAt(line) { return { text: this.text.split('\n')[line] }; },
    };
    documents.push(doc);
    handlers.open(doc);
    return doc;
}

function edit(doc, text) {
    doc.text = text;
    doc.version++;
    handlers.change({ document: doc });
}

async function waitFor(predicate) {
    const deadline = Date.now() + 12000;
    while (!predicate()) {
        assert.ok(Date.now() < deadline, 'timed out waiting for extension result');
        await delay(30);
    }
}

function diagnostics(doc, name = 'seq') {
    return collections.get(name).get(doc.uri.toString());
}

const examples = {
    seq: { valid: 'participant Alice\n', invalid: 'participant Alice\ninvalid syntax !!!\n' },
    fsm: { valid: 'state Idle\ninitial -> Idle\n', invalid: 'state Idle\nIdle -> Missing\n' },
    cls: { valid: 'class Service\n', invalid: 'class Service\nService --> Missing\n' },
};

for (const [language, example] of Object.entries(examples)) {
    test(`${language}: live diagnostics use unsaved edits and clear after fixing`, async () => {
        const doc = open(language, example.valid);
        await waitFor(() => diagnostics(doc) !== undefined);
        assert.deepEqual(diagnostics(doc), []);
        edit(doc, example.invalid);
        await waitFor(() => diagnostics(doc)?.some(d => d.severity === 0));
        assert.equal(diagnostics(doc)[0].range.start.line, 1);
        if (language !== 'seq') { assert.match(diagnostics(doc)[0].message, /Missing/); }
        assert.equal(fs.readFileSync(doc.fileName, 'utf8'), example.valid);
        edit(doc, example.valid);
        await waitFor(() => diagnostics(doc)?.length === 0);
    });

    test(`${language}: save generates drawio and opens beside the source`, async () => {
        const doc = open(language, example.valid);
        const output = doc.fileName.replace(/\.[^.]+$/, '.drawio');
        handlers.save(doc);
        await waitFor(() => previews.some(preview => preview.uri.fsPath === output));
        assert.match(fs.readFileSync(output, 'utf8'), /<mxfile[\s>]/);
        const preview = previews.find(preview => preview.uri.fsPath === output);
        assert.equal(preview.name, 'vscode.open');
        assert.deepEqual(preview.options, { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true });
    });

    for (const command of ['drawiogen.generate', 'drawiogen.preview']) {
        test(`${language}: ${command} generates and opens a split preview`, async () => {
            const doc = open(language, example.valid);
            const output = doc.fileName.replace(/\.[^.]+$/, '.drawio');
            vscode.window.activeTextEditor = { document: doc };
            commands.get(command)();
            await waitFor(() => previews.some(preview => preview.uri.fsPath === output));
            assert.match(fs.readFileSync(output, 'utf8'), /<mxfile[\s>]/);
        });
    }
}

test('editing different diagram files keeps both pending validations', async () => {
    const fsm = open('fsm', examples.fsm.valid);
    const cls = open('cls', examples.cls.valid);
    await waitFor(() => diagnostics(fsm) && diagnostics(cls));
    edit(fsm, examples.fsm.invalid);
    edit(cls, examples.cls.invalid);
    await waitFor(() => diagnostics(fsm)?.length && diagnostics(cls)?.length);
    assert.match(diagnostics(fsm)[0].message, /Missing/);
    assert.match(diagnostics(cls)[0].message, /Missing/);
});

test('closing a document cancels pending validation and clears diagnostics', async () => {
    const doc = open('fsm', examples.fsm.invalid);
    await waitFor(() => diagnostics(doc)?.length);
    edit(doc, examples.fsm.valid);
    doc.isClosed = true;
    handlers.close(doc);
    await delay(700);
    assert.equal(diagnostics(doc), undefined);
});

test('failed class generation reports an error and preserves the existing diagram', async () => {
    const doc = open('cls', examples.cls.invalid);
    const output = doc.fileName.replace(/\.cls$/, '.drawio');
    fs.writeFileSync(output, 'previous diagram');
    handlers.save(doc);
    await waitFor(() => diagnostics(doc, 'seq-generation')?.length);
    assert.match(diagnostics(doc, 'seq-generation')[0].message, /Missing/);
    assert.equal(fs.readFileSync(output, 'utf8'), 'previous diagram');
    assert.ok(!previews.some(preview => preview.uri.fsPath === output));
    assert.deepEqual(messages, []);
});

for (const language of ['cls', 'fsm']) {
    test(`${language}: notes validate, generate and open in the split preview`, async () => {
        const source = language === 'cls'
            ? 'note on Service: Important <text>\\nSecond line\nclass Service\n'
            : 'note on Idle width 180: Important <text>\\nSecond line\nstate Idle\ninitial -> Idle\n';
        const doc = open(language, source);
        await waitFor(() => diagnostics(doc) !== undefined);
        assert.deepEqual(diagnostics(doc), []);
        handlers.save(doc);
        const output = doc.fileName.replace(/\.[^.]+$/, '.drawio');
        await waitFor(() => previews.some(p => p.uri.fsPath === output));
        const xml = fs.readFileSync(output, 'utf8');
        assert.match(xml, /shape=note/);
        assert.match(xml, /dashed=1/);
        assert.match(xml, /Second line/);
        edit(doc, source.replace(/note on (Service|Idle)/, 'note on Missing'));
        await waitFor(() => diagnostics(doc)?.some(d => d.severity === 0));
        assert.match(diagnostics(doc)[0].message, /Unknown note target "Missing"/);
    });
}

test('fsm: unreachable hints clear after adding a path, and skip diagrams without initial', async () => {
    const source = 'state Idle\nstate Lost\ninitial -> Idle\n';
    const doc = open('fsm', source);
    await waitFor(() => diagnostics(doc)?.some(d => d.severity === 3));
    assert.match(diagnostics(doc)[0].message, /"Lost" is unreachable/);
    edit(doc, source + 'Idle -> Lost\n');
    await waitFor(() => diagnostics(doc)?.length === 0);
    edit(doc, 'state Idle\nstate Lost\n');
    await delay(900);
    assert.deepEqual(diagnostics(doc), []);
});

test('hints remain available when Python is not on PATH', async () => {
    const originalPath = process.env.PATH;
    process.env.PATH = temporary;
    try {
        const cls = open('cls', 'package P {\n  class A\n  class A\n  note on Missing: explanation { text }\n');
        const fsm = open('fsm', 'state A\nA -> Missing\n');
        await waitFor(() => diagnostics(cls)?.length && diagnostics(fsm)?.length);
        assert.ok(diagnostics(cls).every(d => d.severity === 3));
        assert.match(diagnostics(cls).map(d => d.message).join('\n'), /Duplicate element.*Unclosed package.*Unknown note target/s);
        assert.match(diagnostics(fsm)[0].message, /Unknown state or choice "Missing"/);
        assert.deepEqual(diagnostics(cls).map(d => d.range.start.line), [2, 0, 3]);
    } finally { process.env.PATH = originalPath; }
});

test('forward references, multiplicities and braces inside actions/member text produce no hints', async () => {
    const cls = open('cls', 'A "B" --> "A" B\nclass A {\n  + Run(): if (ok) { return; }\n}\nclass B\n');
    const fsm = open('fsm', 'A -> B\nstate A {\n  on Tick: if (ok) { Run(); }\n}\nstate B\n');
    await waitFor(() => diagnostics(cls) && diagnostics(fsm));
    assert.deepEqual(diagnostics(cls), []);
    assert.deepEqual(diagnostics(fsm), []);
});

test('hint ranges skip arrow-like text and target names inside multiplicities', async () => {
    const originalPath = process.env.PATH;
    process.env.PATH = temporary;
    try {
        const line = '  A "-->" --> "Missing" Missing';
        const doc = open('cls', 'class A\n' + line + '\n');
        await waitFor(() => diagnostics(doc)?.length);
        assert.equal(diagnostics(doc)[0].severity, 3);
        assert.equal(diagnostics(doc)[0].range.start.character, line.lastIndexOf('Missing'));
    } finally { process.env.PATH = originalPath; }
});
