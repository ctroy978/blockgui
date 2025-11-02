# Workflow Editor (Phase 1)

This repository contains a Phase 1 proof-of-concept for a PySide6-based workflow editor. The tool loads block definitions from a YAML file, lets users drag template blocks from a palette onto a canvas, snap connections between blocks, configure command-line flags, and build a shell-style pipeline that is forwarded to a placeholder `chained_app.py` runner.

## Prerequisites

- Python 3.8+
- A local virtual environment (recommended)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install --upgrade pip
pip install PySide6 pyyaml
```

## Running the Editor

```bash
source .venv/bin/activate  # Activate your virtual environment
python workflow_editor.py
```

The main window displays:

- An **Execute** button (top-left) that generates the pipeline and calls `chained_app.py`.
- An `edsuite path` field (defaults to `../edsuite`) pointing at the real workflow repository.
- **Connect Selected** / **Disconnect Selected** controls to manage links between highlighted blocks.
- A **palette** of template blocks loaded from `blocks.yaml`.
- A **canvas** area where draggable block instances can be placed, snapped, and connected.
- Two pre-seeded blocks (“Stage 1 – OCR”, “Stage 2 – Cleanup”) already connected for convenience.

When you click **Execute**, the app prints the generated command to the terminal and runs:

```bash
python chained_app.py "<generated command>"
```

`chained_app.py` simply echoes the command for debugging.

## YAML Format (`blocks.yaml`)

```yaml
blocks:
  - id: ocr_stage1
    title: "Stage 1 – OCR"
    command: "python batchocr/ocr_tests.py"
    color: blue
    flags:
      - key: input
        label: "Input source"
        long: --input
        short: -i
        placeholder: "PATH or -"
        takes_value: true
      - key: jpeg-quality
        label: "JPEG quality"
        long: --jpeg-quality
        default: "70"
        takes_value: true
  - id: cleanup_stage2
    title: "Stage 2 – Cleanup"
    command: "python cleanocr/cleanup_tests.py"
    color: green
    flags:
      - key: max-tokens
        label: "Max tokens"
        long: --max-tokens
        default: "1200"
        takes_value: true
      - key: keep-original
        label: "Keep original text"
        long: --keep-original
        takes_value: false
        default: false
  # Additional blocks (Stage 3 Evaluation, Stage 4 Reporting, Stage 5 Mail Payloads, Stage 6 SMTP Send) are also defined.
```

- `id`: Internal identifier used when pre-linking blocks.
- `title`: Text rendered on the block/palette entry.
- `command`: Base command inserted into the pipeline before any flags.
- `input` / `output`: Descriptive metadata (not enforced in Phase 1).
- `color`: Port color. Supported keys: blue, gray, green, orange, red (defaults to gray).
- `flags`: Configure command-line options:
  - `long` and optional `short`: Flag names (automatically prefixed with `--` / `-` if omitted).
  - `takes_value`: When `true`, the block renders a value field that is enabled only when the checkbox is ticked.
  - `default`: Initial value for the text field (checkboxes start unchecked unless explicitly set true).
  - `placeholder`, `label`, `description`: Optional UI hints for value fields.

Add new blocks by appending an object to the `blocks` list. They automatically appear in the palette on the next launch.

## How to Test the App

1. Launch the editor (`python workflow_editor.py`).
2. Drag a template block from the palette onto the canvas.
3. Tick a flag’s checkbox to activate it, then adjust the value if applicable.
4. Connect blocks by either snapping their ports together (drag until within ~20 px) or selecting two blocks and clicking **Connect Selected**; use **Disconnect Selected** or the Delete key to break links.
5. Verify the `edsuite path` points at the correct project root, then click **Execute**. The terminal prints the pipeline and executes it inside the edsuite virtualenv (so you'll see the original CLI logs).
6. Select any canvas block or connection line and press `Delete` (or `Backspace`) to remove it if you cloned one by mistake.

## Code Structure

- `workflow_editor.py`: Main application. Contains:
  - `BlockDefinition` / `BlockFlag` dataclasses for YAML data.
  - `CanvasBlock` for draggable blocks with embedded `QLineEdit` / `QCheckBox` controls.
  - `PaletteBlock` templates that spawn new canvased blocks while dragging.
  - `WorkflowEditor` window that manages the scene, snapping, connections, and command generation.
- `blocks.yaml`: Configurable block definitions.
- `chained_app.py`: Minimal subprocess target that prints the generated command.

## Assumptions & Notes

- Palette blocks show the block name and spawn editable clones on drag.
- Blocks expand vertically to fit their flag controls while keeping a minimum 240×110 footprint.
- Every flag starts disabled; the user ticks a checkbox to include it (value-taking flags keep their suggested defaults until enabled).
- Connection validation is not enforced in Phase 1; any blocks can be linked. Only one inbound/outbound connection per block is allowed to keep the pipeline linear.
- `Execute` prepends the edsuite virtualenv (`<edsuite>/.venv`) to `PATH` and runs the generated pipeline from that directory, so the CLI behaves just like it would in the original project.
