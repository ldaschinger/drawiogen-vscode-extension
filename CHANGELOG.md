# Changelog

## 0.0.18

- Add a 256 x 256 extension icon that meets the Marketplace dimension limit.
- Document Python 3.9+ and Graphviz requirements in the extension host environment.
- Record previously shipped features under version 0.0.13.

## 0.0.17

- Try alternative caption positions along existing routes before increasing state spacing.
- Bound the placement search so dense graphs retain the existing spacing fallback.

## 0.0.16

- Shorten initial arrows independently of state spacing, using a 32 px gap for unlabeled starts.
- Retain room for captions on labeled initial arrows and remove the unused leading diagram space.

## 0.0.15

- Center FSM transition captions directly on straight arrow segments.
- Keep captions clear of state boxes, bends, and other captions; add routing space when needed.
- Preserve sharp 90-degree corners and include relocated captions in the diagram bounds.

## 0.0.14

- Route FSM transitions with horizontal and vertical segments and sharp 90-degree corners.
- Place captions beside the orthogonal routes and reserve space for wrapped labels.
- Reject non-orthogonal Graphviz fallback routes and cover return arrows, parallel transitions,
  and self loops in both diagram directions.

## 0.0.13

- Rename the extension to `drawiogen` (`dluk1.drawiogen`), with `drawiogen.generate` and
  `drawiogen.preview` command IDs, and update UI messages and diagnostic sources.
  Update custom keybindings/tasks that reference the previous command IDs.
- Add TextMate highlighting, comment toggling, and bracket configuration for `.cls` and `.fsm`.
- Add lightweight hints for unfinished blocks, duplicate names, unknown references, and FSM
  reachability, including a fallback without Python.
- Add `note on Name [width N]: text` to both parsers/generators, with multiline plain text,
  automatic sizing/placement, and dashed links.
- Register `.cls` and `.fsm` file types and activate the extension when they are opened.
- Run their bundled syntax and semantic checkers on open and after edits, reporting errors in the
  editor and Problems panel.
- Generate sibling `.drawio` files on save and through the Generate/Preview commands for all three
  formats, opening results beside the source.
- Debounce validation separately for each document and discard results for changed or closed documents.
- Add integration coverage using the real Python parsers/generators and a VS Code host stub.
- Document feature parity, notes/hints behavior, remaining language differences, and the Graphviz
  requirement for `.cls` and `.fsm` generation.

## 0.0.8
- Input validation and security hardening (path traversal protection, subprocess timeouts, file size limits)

## 0.0.7
- Fix syntax highlighting for indented lines inside `alt`/`loop`/`par` blocks

## 0.0.6
- Syntax and semantic diagnostics: red squiggles for parse errors, grey/blue dotted hints for semantic issues (unclosed blocks, missing deactivations, unknown participants)

## 0.0.5
- Syntax highlighting for `.seq` files (keywords, arrows, participant names, labels, comments)

## 0.0.4
- Bundle `lark` with the extension — Python is the only requirement, no `pip install` needed

## 0.0.3
- Remove editor title button

## 0.0.1 – 0.0.2
- Initial release
