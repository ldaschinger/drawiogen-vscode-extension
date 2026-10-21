# drawiogen

Generate and validate editable draw.io diagrams from text in VS Code: sequence diagrams (`.seq`), class/component diagrams (`.cls`), and state machines (`.fsm`). Save a source file to generate its sibling `.drawio` file and open it beside the source.

Commands in the Command Palette:

- `drawiogen: Generate .drawio from current diagram file` (`drawiogen.generate`)
- `drawiogen: Open Preview to the Side` (`drawiogen.preview`)

Previously named `drawioseq`. The extension ID is now `dluk1.drawiogen`; replace the old extension when installing this version and update custom keybindings or tasks to use the new command IDs above.

## Diagram text authoring reference

Instructions for AI agents writing diagram source files. These are custom languages; follow the syntax in this file exactly. Choose the file extension for the diagram you need:

- [`.seq` — sequence diagrams](#seq--sequence-diagrams)
- [`.cls` — class and component diagrams](#cls--class-and-component-diagrams)
- [`.fsm` — finite state machine diagrams](#fsm--finite-state-machine-diagrams)
- [Anchored notes in `.cls` and `.fsm`](#notes-in-cls-and-fsm)

Write raw diagram text into the source file. Use meaningful identifiers, declare referenced elements as required by each language, and express display names in labels. Preserve the source file as the authoring input; regenerate the `.drawio` output after changes.

## Shared authoring rules

- Write one statement or member per physical line. Indentation is optional and does not determine structure.
- Blank lines and whole-line comments beginning with `//` (optionally indented) are ignored. **Inline comments are not supported**: trailing `// ...` may become label text or cause an error.
- Keywords, identifiers, and references are case-sensitive.
- Identifiers match `[A-Za-z0-9_]+`. Prefer names such as `MotorCtrl` or `Motor_Ctrl`; put spaces, punctuation, and human-readable names in labels instead. References always use the identifier, never the display label. Avoid keyword names for identifiers.
- Where a statement uses `: text`, put at least one space or tab after the colon and supply nonempty text. Omit both the colon and text when an optional label is absent.
- Text following a label colon is generally unquoted. Quotes there are display characters, not string delimiters. Quoted sequence group titles and class multiplicities are explicit exceptions.
- Use a single optional `title: Diagram title` near the beginning. `.cls` and `.fsm` also accept `direction: TB` or `direction: LR` (default `TB`). `.seq` has no `direction` directive.
- For `.cls` and `.fsm` blocks, put `{` on the declaration line and `}` alone on a later line. Do not use semicolons or one-line bodies such as `class A { + Run() }`.
- LF and CRLF input are accepted; a final newline is recommended and is added by the parsers if missing.
- Emit raw diagram text into source files, without Markdown fences, `@startuml`, or Mermaid headers. The examples below include fences only for readability.

## Validate and generate every authored file

Run the commands below from this directory. Python 3 is required; Lark is bundled. Generation of `.fsm` and `.cls` also requires Graphviz `dot`, and `.cls` relationship routing requires `neato`.

Save the source, then run its checker with the source on standard input:

```bash
python3 vendor/seqgen/check.py < Example.seq
python3 vendor/clsgen/check.py < Example.cls
python3 vendor/fsmgen/check.py < Example.fsm
```

Each prints a JSON array: `[]` means the checker found no error; an error object contains `line`, `col`, and `message` (one-based positions). Inspect this JSON: checker processes do not signal a reported diagram error through a nonzero exit status. The sequence checker performs syntax parsing only; the class and state machine checkers also run their parser's semantic validation.

Fix every reported error, then run the matching generator and require a successful exit:

```bash
python3 vendor/seqgen/main.py Example.seq
python3 vendor/clsgen/main.py Example.cls
python3 vendor/fsmgen/main.py Example.fsm
```

Each writes a sibling `.drawio` file. To choose a different output path, pass `-o`:

```bash
python3 vendor/clsgen/main.py Example.cls -o ClassOverview.drawio
python3 vendor/fsmgen/main.py Example.fsm -o StateMachine.drawio
```

Generation replaces the output, including manual edits to that file. Use distinct basenames for different diagrams: `Example.seq`, `Example.cls`, and `Example.fsm` all default to `Example.drawio`. Validate the actual saved source, fix errors, and regenerate before considering the diagram complete.

## Notes in `.cls` and `.fsm`

Use the same anchored statement in either language:

```text
note on <identifier> [width <pixels>]: <plain text>
```

The angle-bracketed names are placeholders; square brackets mean the width option is optional. Examples you can generate independently:

```cls
class Service
note on Service: Counts successful calls.\nResets after restart.
note on Service width 300: A second note on the same class.
```

```fsm
state Idle
initial -> Idle
note on Idle width 220: Waiting for Start.\nReset runs on entry.
note on initial: Entry into the machine.
```

- References use the declared identifier, not a display label, and may precede the declaration. Unknown note targets produce a positioned parser error.
- `.cls` notes can target any declared class, interface, enum, component, or package, including nested elements. Write notes at top level or inside package/component containers; class/interface/enum bodies still contain only members/literals.
- `.fsm` notes can target states, choices, and `initial`/`final` when those pseudostates are drawn by transitions. Write notes at top level, outside state action bodies. Transitions and individual members/actions are not note targets.
- Keep a note on one physical source line. A literal `\n` starts a displayed line; long text also wraps automatically. HTML is escaped as text, including `<br/>`.
- Width defaults to 240 pixels and accepts integers from 80 to 1000. Height grows with the wrapped text. Empty text and invalid widths are rejected. The only optional argument in this note syntax is `width`.
- Notes appear as folded-corner callouts linked to their targets. Their placement and height are automatic. Write them in the intended reading order; they appear in a column to the right of the diagram.

Additional complete examples: [ClassNotes.cls](vendor/clsgen/examples/ClassNotes.cls) and [StateNotes.fsm](vendor/fsmgen/examples/StateNotes.fsm).

## `.seq` — sequence diagrams

Use this language for participants, messages, activations, and sequence frames. The [bundled grammar](vendor/seqgen/syntax.lark) and [parser](vendor/seqgen/seqast.py) define the accepted syntax.

### Complete example

Save as `MotorStartup.seq`:

```seq
title: Motor startup
participant App: Application
participant Ctrl width 180 spacing 80: Motor controller
participant Driver: Motor driver

App ->+ Ctrl: Start()
Ctrl ->+ Driver: Enable()
Driver -->>- Ctrl: Ready
alt supply available
  Ctrl ->| Driver: SetCurrent(100)
else supply unavailable
  Ctrl: Record fault
end
note on Ctrl width 180 height 50 dx 20: Result returned to caller
vertical offset 50
Ctrl -->>- App: Startup result
```

### Title and participants

```seq
title width 240 height 50: Motor startup<br/>Normal operation
participant App
participant Ctrl width 200 spacing 100: Motor controller
```

A title is optional and creates an enclosing UML frame. Its `width` and `height` adjust the title tab, not the whole diagram (defaults: 160 and 30).

Declare every participant explicitly before using it. Identifiers must be unique. Participants appear from left to right in declaration order. `: label` changes the displayed name; without it, the identifier is displayed. Participant `width` defaults to 160; `spacing` defaults to 40 and measures the gap from the preceding participant. The first participant has no preceding gap.

All sequence geometry values are integers, not decimal numbers or values with units. Use positive dimensions. Signed values are useful for offsets and frame extension. Specify each option at most once.

Sequence labels support HTML such as `<br/>` for a visible line break; keep the source statement on one physical line.

### Messages and arrow notation

General form (angle-bracketed names below are placeholders):

```text
<sender> <line><arrowhead><activation> <receiver>[: <message>]
```

Put whitespace between sender, arrow, and receiver. The arrow itself is contiguous. The message is optional:

```seq
App -> Ctrl: Start()
Ctrl -->> App
```

Combine one line style, one arrowhead, and optionally one activation suffix:

| Part | Syntax | Meaning |
|---|---|---|
| Line | `-` | Solid |
| Line | `--` | Dashed |
| Arrowhead | `>` | Filled block |
| Arrowhead | `>>` | Open |
| Activation | omitted | Leave activation stacks unchanged |
| Activation | `+` | Activate the receiver |
| Activation | `-` | Deactivate the sender after sending |
| Activation | `\|` | Activate the receiver for this message, then immediately deactivate it |

For example, `->`, `->>`, `-->`, and `-->>` are the four line/arrowhead combinations. `->+` opens a receiver activation; `-->>-` closes a sender activation. Arrows point from the first participant to the second; reverse the participants to draw a message in the other direction.

### Activations and self calls

```seq
activate App Ctrl
App ->+ Ctrl: Nested call
Ctrl -->>- App: Nested result
deactivate App Ctrl
```

`activate` and `deactivate` accept one or more participant identifiers. Multiple names in one statement share a vertical position. Activations form a stack: each `+` or explicit activation must eventually be matched by a deactivation. Deactivating an inactive participant fails, and **every participant must be inactive at end of file**.

Self calls use the same participant on both ends:

```seq
Ctrl -> Ctrl: Check state
Ctrl -->>| Ctrl: Brief local work
Ctrl ->+ Ctrl: Begin nested work
deactivate Ctrl
Ctrl: Update cached value
```

The last line is shorthand for a solid self call with temporary activation (`->|`). This shorthand requires message text. Self calls support no activation suffix, `+`, or `|`; a `-` suffix on a self call is invalid. Use an explicit `deactivate` to close it.

### Found and lost messages

Use a found message when its sender is outside the diagram; use a lost message when its receiver is outside the diagram:

```seq
found left -> App: External event
found right 140 ->+ Ctrl: Request
Ctrl -->>- lost right 120: Result
App -> lost left: Forward event
```

`left` and `right` select the side of the named participant. The optional integer is the message width (default 100). Found messages allow no activation suffix or `+`; lost messages allow no suffix or `-`. A lost message with `-` still requires an active sender. Both support either line style and arrowhead, with optional message text.

### Frames and sections

Frames can be nested and each needs a matching `end`. In the examples in this subsection, `App` and `Ctrl` are already declared participants.

`opt`, `loop`, `break`, and `critical` each wrap one section. Their descriptive text is optional:

```seq
opt diagnostics enabled
  App -> Ctrl: ReadDiagnostics()
end
loop while work remains
  App -> Ctrl: ProcessNext()
end
break on fault
  Ctrl -> App: ReportFault()
end
critical update shared state
  App -> Ctrl: Commit()
end
```

Use `alt` / `else` for alternatives. Additional `else` sections are allowed; an unlabeled `else` displays `else`:

```seq
alt ready
  App -> Ctrl: Start()
else busy
  Ctrl -> App: RetryLater()
else
  Ctrl -> App: Reject()
end
```

Use `par` / `and` for parallel sections. Opening and section labels are optional, and additional `and` sections are allowed:

```seq
par control work
  App -> Ctrl: Update()
and telemetry
  Ctrl -> App: Publish()
end
```

Use `group "title"` for a custom frame title. The quoted title is required and should be nonempty. Optional text after the title labels the first section; additional sections use `section` with optional text:

```seq
group "Startup checks" first check
  App -> Ctrl: CheckSupply()
section second check
  App -> Ctrl: CheckDriver()
end
```

A group title may include an escaped quote (`\"`). `else`, `and`, and `section` belong only to their corresponding frame types.

Frames describe presentation; the generator processes all sections in source order. Activation state is not reset between alternative or parallel branches. Balance activation stacks across the actual file order.

Frame height follows the vertical position. Width is derived from participants/messages processed inside it, including nested frames. Include content that establishes a width, such as a message, self call, or activation; a frame containing only comments, notes, or offsets cannot be laid out.

### Notes, spacing, and frame width

```seq
note on Ctrl: Check supply first
note on Ctrl width 200 height 70 dx 30 dy -10: Supply must remain<br/>within range
vertical offset 80
vertical offset -20

opt detailed request
  App -> Ctrl: Request with a long label
  extend frame 120
  extend frame -60
end
```

A note is anchored at the participant's lifeline and current vertical position. Its optional `width` / `height` default to 100 / 40; `dx` / `dy` default to zero and shift it right/down (negative values shift left/up). Notes neither advance the vertical position nor enlarge a frame, so add spacing or extend the frame when needed.

`vertical offset N` shifts the current vertical position by the signed integer `N`. Negative offsets can produce overlapping content.

`extend frame N` enlarges the current frame at that point: positive values extend its right edge, negative values its left edge. Place it after content has established the frame width. Outside a nested frame, it affects the outer diagram bounds, including the title frame when present.

### Sequence validation

The syntax checker parses the language; generation also checks activation stacks, participant references, and frame layout. Require successful generation as well as an empty checker result. Common causes of generation failure are duplicate participants, unknown references, duplicate titles, unbalanced activations, and empty frames.

## `.cls` — class and component diagrams

The same language describes class details and component/package structure. It is implemented by the [bundled grammar](vendor/clsgen/syntax.lark), [parser and validation](vendor/clsgen/clsast.py), and [layout code](vendor/clsgen/layout.py).

### Complete example

Save as `MotorModel.cls`:

```cls
title: Motor control model
direction: TB

package Control : Control software {
  component MotorModule : Motor module {
    interface IMotor {
      + Start(): void
      + Stop(): void
    }
    class MotorCtrl : Motor controller <<object>> {
      - current_mA: uint16_t
      # enabled: bool
      + Start(): void
      + Stop(): void
    }
    enum MotorMode {
      Idle
      Running
      Fault
    }
  }
}
component Driver: Motor driver

MotorCtrl ..|> IMotor
MotorCtrl "1" --> "1" Driver: commands
MotorCtrl --> MotorMode: mode
```

### Elements, labels, and stereotypes

Leaf elements have no body:

```cls
class MotorCtrl
interface IMotor: Motor interface
enum Mode
component Driver: Motor driver
class Context: Execution context <<object>>
```

The kinds are `class`, `interface`, `enum`, `component`, and `package`. A `package` always needs a container body; it has no leaf form.

An optional label follows the identifier. A stereotype, if present, follows the label (or the identifier when no label is used): `<<text>>`. Interfaces default to `<<interface>>` and enums to `<<enumeration>>`; an explicit stereotype replaces the default. Leaf components also accept stereotypes. Container declarations (`package` or `component` with a body) do not accept stereotypes.

Display labels cannot contain `{` or `<`; `<` introduces stereotype syntax. HTML is not a formatting language here: labels, members, stereotypes, and relationship text are escaped for display. Keep each value on one physical line.

### Class/interface members and enum literals

```cls
class Controller {
  - count: uint32_t
  + Start(): void
  # ResetInternal(): void
  ~ ProcessPending(): bool
}
interface IController {
  + Start(): void
}
enum Mode {
  Idle
  Running
  Fault
}
```

Class and interface members must start with a visibility marker:

| Marker | Conventional meaning |
|---|---|
| `+` | Public |
| `-` | Private |
| `#` | Protected |
| `~` | Package/internal |

The rest of a member line is display text; the parser does not validate C/C++ declarations or types. A line containing `(` is treated as a method; other members are attributes. Rendering groups attributes before methods, retaining order within each group.

An enum entry is a plain line starting with a letter or underscore, with no visibility marker. For example, `Idle` and `Running = 1` are accepted. Class, interface, and enum bodies may be empty, provided braces remain on separate lines. Their bodies contain only members/literals, not nested elements, relationships, or layout directives.

### Packages, component containers, and nesting

```cls
package Software: Software layers {
  component ControlModule: Control {
    interface IControl
    class ControlImpl
  }
  component HardwareDriver
}
ControlImpl ..|> IControl
ControlImpl ..> HardwareDriver: uses
```

Packages and components may contain nested packages, components, classes, interfaces, and enums. Put at least one element in every container. A component without braces is a leaf; one with child elements is a container. Classes and interfaces use braces for members, never child elements.

**Identifiers are globally unique**, including across different containers. There is no qualified-name syntax such as `Software.ControlImpl`; reference `ControlImpl` directly. For repeated concepts, choose distinct identifiers and reuse a display label if desired.

Relationships may be written at top level or inside a container; they always resolve against the global identifier table. Forward references are supported, though declarations followed by relationships are easier to read. Both relationship endpoints must be leaves: classes, interfaces, enums, or components without children. A package or component containing other elements cannot be an endpoint.

### Relationships and multiplicities

General form:

```text
<source> ["source multiplicity"] <arrow> ["target multiplicity"] <target>[: <label>]
```

Whitespace separates identifiers, multiplicities, and arrows. Both multiplicities and the label are optional. Multiplicities require double quotes and cannot contain double quotes or physical newlines:

```cls
Whole "1" *-- "0..*" Part: owns
Implementation ..|> Contract
Child --|> Parent
Client ..> Service: uses
```

Use only these arrows:

| Arrow | Meaning and orientation |
|---|---|
| `--\|>` | Inheritance: source child to target parent, hollow triangle at target |
| `..\|>` | Realization: source implementation to target contract, dashed with hollow triangle at target |
| `*--` | Composition: filled diamond at source (the whole) |
| `o--` | Aggregation: hollow diamond at source (the whole) |
| `-->` | Directed association: open arrow at target |
| `..>` | Dependency: dashed open arrow at target |
| `--` | Undirected association: solid line |
| `..` | Undirected dashed line |

Reverse the source/target identifiers to change orientation; reversed arrow spellings are not supported. Label and multiplicity values are display text, not validated constraints.

### Layout directives

`direction: TB` lays out the graph top to bottom; `direction: LR` uses left to right. `TB` is the default. For inheritance and realization, automatic layout places the parent/interface before the child/implementation along that direction. Other relationships follow their source-to-target orientation as a layout hint.

`arrange: LR` or `arrange: TB` places whole top-level elements in declaration order, in a row or column. This is separate from `direction`, which still guides the graph layout within each block. Without `arrange`, top-level placement is automatic. Write global directives at top level.

Additional layout directives take **at least two distinct identifiers**, separated by whitespace:

| Directive | Placement and requirements | Effect |
|---|---|---|
| `same-size: A B` | Top level; requires `arrange: LR` or `arrange: TB`; names top-level package/component containers | Equalizes the containers' width and height |
| `align-horizontal: A B` | Top level; requires `arrange: LR`; names leaves inside different top-level blocks | Aligns the leaves' vertical centers, moving their branches as needed |
| `top-row: A B` | Inside a package/component container; requires `direction: TB`; at most one per container; names its direct leaf children | Places those children on the container's top graph rank |

Names can be declared later. A nested descendant is not a direct child for `top-row`. `align-horizontal` may name nested leaves, but each must belong to a different top-level block. Avoid conflicting alignment groups; combine leaves that should share a horizontal line into one group. Overlapping `same-size` groups propagate the shared size.

This complete layout example can be generated as its own `.cls` file:

```cls
title: Aligned subsystems
direction: TB
arrange: LR
same-size: ControlBlock DriverBlock
align-horizontal: MotorCtrl DriverImpl

package ControlBlock: Control {
  top-row: IMotor IMonitor
  interface IMotor
  interface IMonitor
  class MotorCtrl
}
package DriverBlock: Driver {
  class DriverImpl
}
MotorCtrl ..|> IMotor
MotorCtrl ..|> IMonitor
MotorCtrl ..> DriverImpl: commands
```

Leaf siblings inside each container automatically share the largest sibling width and height. Sizes are calculated from content; `.cls` has no explicit node coordinate, `width`, `height`, or spacing statements; note widths are configured separately.

### Class/component validation

Parsing also validates identifier uniqueness, relationship endpoints, member prefixes, enum literals, and layout directive scopes/references. Generation additionally runs Graphviz and checks layout/routing constraints. If routing reports insufficient clearance, simplify the connections or adjust the container/layout structure.

## `.fsm` — finite state machine diagrams

This language describes a flat state graph with state actions and choice diamonds. It is implemented by the [bundled grammar](vendor/fsmgen/syntax.lark), [parser and validation](vendor/fsmgen/fsmast.py), and [layout code](vendor/fsmgen/layout.py).

### Complete example

Save as `MotorControl.fsm`:

```fsm
title: Motor control
direction: TB

state Idle {
  entry: DisableMotor()
  on Tick: UpdateDiagnostics()
}
state Running: Motor running {
  entry: EnableMotor()
  exit: DisableMotor()
  on Tick: UpdateCurrent()
}
state Fault {
  entry: ReportFault()
}
choice SupplyOk: Supply available?

initial -> Idle
Idle -> SupplyOk: Start requested
SupplyOk -> Running: [supply available]
SupplyOk -> Fault: [supply unavailable]
Running -> Idle: Stop requested / ClearRequest()
Running -> Fault: Overcurrent
Fault -> final: Shutdown
```

### States and actions

Declare a state with its identifier and optional label, with or without an action body:

```fsm
state Idle
state Running: Motor running
state Waiting: Waiting for command {
  entry: StartTimer()
  entry: ClearPendingCommand()
  exit: StopTimer()
  on Tick: UpdateTimeout()
  on Cancel: ClearPendingCommand()
}
```

State bodies accept only:

```text
entry: <action text>
exit: <action text>
on <event identifier>: <action text>
```

Multiple entries, exits, and internal event lines are allowed. Rendering groups entries first, exits second, and internal events last; order is preserved within each group. `on` event identifiers follow the same identifier rule as state names. Action text is displayed literally, without validation or execution as C/C++.

`on Event: Action()` documents an internal handler. It does not create an edge, even if the text says `Goto SomeState`; add an explicit transition for a visible state change. An action block is not a composite state: nested states, transitions, choices, and directives are not allowed inside it. Empty state bodies are accepted.

### Choices

```fsm
choice SupplyOk: Supply available?
```

A choice is a diamond identified by a unique name and optional label. It has no body. Its incoming and outgoing edges use ordinary transition syntax. Put guard/branch descriptions in outgoing transition labels:

```fsm
Idle -> SupplyOk: Start
SupplyOk -> Running: [supply available]
SupplyOk -> Fault: [else]
```

State and choice identifiers share one global namespace. Forward references in transitions are supported. Choices do not automatically create branches; declare each edge explicitly. The parser does not enforce branch counts, mutually exclusive guards, or reachability.

### Transitions and pseudostates

General form:

```text
<source> -> <target>[: <transition label>]
```

Only the `->` arrow is supported. Labels are optional; event/guard/action notation is a useful convention:

```fsm
initial -> Idle
Idle -> Running: Start [supply_ok] / EnableMotor()
Running -> Running: Refresh / UpdateCurrent()
Running -> final
```

The entire label is free text. Brackets, `/`, event names, conditions, and action calls are not separately parsed or executed. Self transitions and multiple edges between the same nodes are accepted.

The exact lowercase names `initial` and `final` are reserved pseudostates. Reference them in transitions without declarations; their symbols are generated only when referenced.

- No transition may enter `initial`.
- At most one transition may leave `initial`.
- No transition may leave `final`.
- Multiple transitions may enter `final`.
- Neither `state initial` / `state final` nor choices with those names are allowed.
- Both pseudostates are optional; the parser does not require an initial or final transition.

Every other transition endpoint must name a declared state or choice. Names are case-sensitive, so `Initial` is a different, ordinary identifier.

### Layout, labels, and supported scope

Write layout directives at top level, outside state action bodies:

| Directive | Accepted value | Effect/default |
|---|---|---|
| `direction: TB` | `TB` or `LR` | Top-to-bottom or left-to-right placement; default `TB` |
| `transition-spacing: 110` | Positive integer or decimal, in pixels | Minimum gap between graph ranks, in addition to space for labels; default 50.4 pixels |
| `transition-label-width: 300` | Positive integer or decimal, in pixels | Width used to wrap transition labels; when omitted, labels wrap at about 32 characters |

Increasing `transition-spacing` gives transition paths more room along the layout direction. Increase `transition-label-width` to keep longer labels on fewer lines. Explicit `\n` line breaks remain in effect. These settings apply to the whole diagram; write each at most once.

These formatting settings belong in the `.fsm` source; the generation command is unchanged. After editing them, rerun `python3 vendor/fsmgen/main.py Example.fsm` to update the diagram.

Complete example with transition layout settings:

```fsm
title: Transition layout
direction: TB
transition-spacing: 110
transition-label-width: 300
state Idle
state Running
initial -> Idle
Idle -> Running: Start [supply_ok] / EnableMotor()
Running -> Idle: Stop / DisableMotor()
```

State positions and dimensions are calculated automatically:

- State boxes grow to fit their titles and actions. Long action text wraps, and the box height grows to fit the resulting lines. The preferred maximum width is 420 pixels; long titles or unbroken identifiers may make a box wider. Explicit state width and height directives are not supported.
- The diagram title tab grows to fit its text.
- The initial marker occupies the first rank: above the states for `TB`, or to their left for `LR`. Placement follows the entry path when arranging cycles.
- Transition paths and label positions are preserved in the generated `.drawio`, giving opposing arrows and parallel transitions separate routes. Inspect dense graphs after generation; routing does not guarantee that every possible graph is free of overlaps. Use the transition spacing and label width settings above when more room is needed.

Set note widths with the shared note syntax above.

State labels may contain spaces and punctuation but cannot contain `{`. Titles, labels, and actions are escaped for display. Use plain text; HTML such as `<br/>` is displayed literally. State display labels, entry/exit/internal-action text, and transition labels support the literal two-character sequence `\n` for a displayed line break. Transition labels and state action text also wrap automatically:

```fsm
Running -> Fault: Overcurrent\n[current > limit] / DisableMotor()
```

Keep each statement on one physical source line. Use multiple `entry:` or `exit:` statements for separate actions, or literal `\n` inside one action to control its displayed line breaks:

```fsm
state Waiting: Waiting for\nconfirmation {
  entry: StartTimer()\nClearPendingCommand()
}
```

Choice labels and diagram titles are single-line text. Do not use physical multiline strings.

Keep the state graph flat. To describe a hierarchy, use distinct flat identifiers with descriptive labels, or write separate diagram files. Put transitions and notes outside state action bodies.

### State machine validation

Parsing checks syntax, duplicate state/choice identifiers, reserved names, unknown transition/note targets, note widths, positive transition layout values, and the initial/final restrictions above. Ensure the declared states and transitions match the system being documented; event, guard, and action text are descriptive. Generate the diagram as well to verify layout and output.
