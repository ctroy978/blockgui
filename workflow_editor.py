#!/usr/bin/env python
"""
Workflow editor proof-of-concept built with PySide6.

The editor loads block definitions from a YAML file, renders template blocks in
an on-canvas palette, allows spawning editable blocks, and snaps connections
between compatible ports. Selecting Execute builds a pipeline command string
and forwards it to chained_app.py for demonstration purposes.
"""

from __future__ import annotations

import math
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QLineEdit,
    QMainWindow,
    QLabel,
    QMessageBox,
    QPushButton,
)


@dataclass
class BlockFlag:
    """Represents a single command-line flag for a block."""

    key: str
    label: str
    long_option: str
    short_option: Optional[str] = None
    default_value: str = ""
    takes_value: bool = True
    default_checked: bool = False
    placeholder: Optional[str] = None
    description: Optional[str] = None

    def display_label(self) -> str:
        """Return a friendly label that shows long/short options."""
        parts: List[str] = []
        if self.long_option:
            parts.append(self.long_option)
        if self.short_option:
            parts.append(f"({self.short_option})")
        return " ".join(parts) if parts else self.label or self.key


@dataclass
class BlockDefinition:
    """Represents a block definition parsed from YAML."""

    identifier: str
    title: str
    command: str
    input: str = "any"
    output: str = "any"
    color: str = "gray"
    include_in_bootstrap: bool = True
    flags: List[BlockFlag] = field(default_factory=list)


@dataclass
class FlagWidget:
    """Holds references to flag widgets embedded in a block."""

    flag: BlockFlag
    checkbox_proxy: Optional[QGraphicsProxyWidget] = None
    value_proxy: Optional[QGraphicsProxyWidget] = None

    def checkbox(self) -> Optional[QCheckBox]:
        widget = self.checkbox_proxy.widget() if self.checkbox_proxy else None
        return widget if isinstance(widget, QCheckBox) else None

    def value_edit(self) -> Optional[QLineEdit]:
        widget = self.value_proxy.widget() if self.value_proxy else None
        return widget if isinstance(widget, QLineEdit) else None


COLOR_MAP: Dict[str, str] = {
    "blue": "#1E88E5",
    "gray": "#808080",
    "green": "#2E7D32",
    "orange": "#FB8C00",
    "red": "#C62828",
}


def ensure_prefixed(option: Optional[str], prefix: str) -> str:
    """Ensure options start with the expected dash prefix."""
    if not option:
        return ""
    option = option.strip()
    if not option:
        return ""
    if option.startswith("-"):
        return option
    return f"{prefix}{option}"


def resolve_color(name: str) -> QColor:
    """Return a QColor for the provided name, defaulting to gray."""
    hex_value = COLOR_MAP.get(name.lower(), COLOR_MAP["gray"])
    return QColor(hex_value)


def parse_flag(data: Dict[str, Any]) -> Optional[BlockFlag]:
    """Convert a YAML flag entry into a BlockFlag instance."""
    long_option = ensure_prefixed(data.get("long") or data.get("name"), "--")
    short_option = ensure_prefixed(data.get("short"), "-") if data.get("short") else None

    key = str(data.get("key") or data.get("name") or long_option or data.get("short") or "flag").strip()
    key = key or "flag"

    label = str(data.get("label") or "").strip()
    if not label:
        label = long_option or key

    takes_value = bool(data.get("takes_value", True))
    raw_default = data.get("default", "" if takes_value else False)
    if takes_value:
        default_value = "" if raw_default is None else str(raw_default)
        default_checked = False
    else:
        default_value = ""
        default_checked = bool(raw_default)

    placeholder = str(data.get("placeholder", "")).strip() or None
    description = str(data.get("description", "")).strip() or None

    return BlockFlag(
        key=key,
        label=label,
        long_option=long_option,
        short_option=short_option,
        default_value=default_value,
        takes_value=takes_value,
        default_checked=default_checked,
        placeholder=placeholder,
        description=description,
    )


def load_block_definitions(yaml_path: Path) -> List[BlockDefinition]:
    """
    Load block definitions from the provided YAML file.

    On failure a single fallback block is returned so the UI stays operable.
    """
    if not yaml_path.exists():
        print(f"[workflow_editor] Missing {yaml_path}, loading fallback block.")
        return [
            BlockDefinition(
                identifier="default",
                title="Default Block",
                command="echo 'default block'",
                color="gray",
                include_in_bootstrap=True,
            )
        ]

    try:
        with yaml_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"[workflow_editor] Failed to read {yaml_path}: {exc}")
        return [
            BlockDefinition(
                identifier="default",
                title="Default Block",
                command="echo 'default block'",
                color="gray",
                include_in_bootstrap=True,
            )
        ]

    blocks_data = raw.get("blocks", [])
    definitions: List[BlockDefinition] = []
    for entry in blocks_data:
        if not isinstance(entry, dict):
            continue
        identifier = str(
            entry.get("id")
            or entry.get("name")
            or entry.get("command")
            or f"block_{len(definitions) + 1}"
        ).strip()
        if not identifier:
            identifier = f"block_{len(definitions) + 1}"
        title = str(entry.get("title") or identifier).strip()
        command = str(entry.get("command") or identifier).strip()
        input_type = str(entry.get("input", "any"))
        output_type = str(entry.get("output", "any"))
        color = str(entry.get("color", "gray"))
        include_in_bootstrap = bool(entry.get("include_in_bootstrap", True))

        flags: List[BlockFlag] = []
        raw_flags = entry.get("flags", [])
        if isinstance(raw_flags, list):
            for flag_entry in raw_flags:
                if isinstance(flag_entry, dict):
                    flag = parse_flag(flag_entry)
                    if flag and flag.long_option:
                        flags.append(flag)

        definitions.append(
            BlockDefinition(
                identifier=identifier,
                title=title,
                command=command,
                input=input_type,
                output=output_type,
                color=color,
                include_in_bootstrap=include_in_bootstrap,
                flags=flags,
            )
        )

    if definitions:
        return definitions

    print(f"[workflow_editor] No usable block entries found in {yaml_path}, loading fallback block.")
    return [
        BlockDefinition(
            identifier="default",
            title="Default Block",
            command="echo 'default block'",
            color="gray",
            include_in_bootstrap=True,
        )
    ]


class PortItem(QGraphicsEllipseItem):
    """Circular port used for input/output connections."""

    RADIUS = 5.0

    def __init__(self, parent: QGraphicsItem, color: QColor):
        super().__init__(-PortItem.RADIUS, -PortItem.RADIUS, 2 * PortItem.RADIUS, 2 * PortItem.RADIUS, parent)
        self.setBrush(color)
        self.setPen(QPen(Qt.black, 1))
        self.setAcceptedMouseButtons(Qt.NoButton)


class CanvasBlock(QGraphicsRectItem):
    """Interactive block placed on the canvas."""

    BASE_WIDTH = 240.0
    BASE_HEIGHT = 110.0

    def __init__(self, definition: BlockDefinition, editor: "WorkflowEditor"):
        super().__init__(0.0, 0.0, CanvasBlock.BASE_WIDTH, CanvasBlock.BASE_HEIGHT)
        self.definition = definition
        self.editor = editor
        self.flag_widgets: List[FlagWidget] = []

        self.setBrush(QColor("#F5F5F5"))
        self.setPen(QPen(Qt.black, 1))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )

        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)

        command_font = QFont()
        command_font.setPointSize(8)

        self._title = QGraphicsTextItem(self.definition.title, self)
        self._title.setDefaultTextColor(Qt.black)
        self._title.setFont(title_font)

        self._command_text = QGraphicsTextItem(self.definition.command, self)
        self._command_text.setDefaultTextColor(Qt.darkGray)
        self._command_text.setFont(command_font)

        port_color = resolve_color(self.definition.color)
        self.input_port = PortItem(self, port_color)
        self.output_port = PortItem(self, port_color)

        self._layout_content()

    # ----------------------------
    # Layout and content rendering
    # ----------------------------
    def _layout_content(self) -> None:
        """Create and position child widgets inside the block."""
        rect = self.rect()
        text_width = rect.width() - 10.0

        self._title.setTextWidth(text_width)
        self._title.setPos(5.0, 5.0)

        title_height = self._title.boundingRect().height()

        self._command_text.setTextWidth(text_width)
        self._command_text.setPos(5.0, 5.0 + title_height)
        command_height = self._command_text.boundingRect().height()

        for widget in self.flag_widgets:
            for proxy in (widget.checkbox_proxy, widget.value_proxy):
                if proxy and proxy.scene():
                    proxy.scene().removeItem(proxy)
        self.flag_widgets.clear()

        y_cursor = 5.0 + title_height + command_height + 6.0
        available_width = rect.width() - 10.0

        for flag in self.definition.flags:
            checkbox = QCheckBox(flag.display_label())
            checkbox.setChecked(flag.default_checked)
            checkbox_proxy = QGraphicsProxyWidget(self)
            checkbox_proxy.setWidget(checkbox)
            checkbox_proxy.setPos(5.0, y_cursor)

            y_cursor += checkbox.sizeHint().height() + 2.0

            value_proxy: Optional[QGraphicsProxyWidget] = None
            if flag.takes_value:
                value_edit = QLineEdit(flag.default_value)
                if flag.placeholder:
                    value_edit.setPlaceholderText(flag.placeholder)
                value_edit.setMaximumWidth(int(available_width) - 20)
                value_edit.setEnabled(checkbox.isChecked())
                value_proxy = QGraphicsProxyWidget(self)
                value_proxy.setWidget(value_edit)
                value_proxy.setPos(25.0, y_cursor)
                checkbox.toggled.connect(value_edit.setEnabled)  # type: ignore[arg-type]
                y_cursor += value_edit.sizeHint().height() + 6.0
            else:
                y_cursor += 4.0

            self.flag_widgets.append(
                FlagWidget(flag=flag, checkbox_proxy=checkbox_proxy, value_proxy=value_proxy)
            )

        min_height = max(CanvasBlock.BASE_HEIGHT, y_cursor + 4.0)
        if not math.isclose(self.rect().height(), min_height):
            self.setRect(0.0, 0.0, self.rect().width(), min_height)

        # Position ports centered vertically on left/right edges.
        self.input_port.setPos(self.rect().left(), self.rect().height() / 2.0)
        self.output_port.setPos(self.rect().right(), self.rect().height() / 2.0)

    # ------------------------
    # Accessors and utilities
    # ------------------------
    def flag_arguments(self) -> List[str]:
        """Return flag arguments based on current UI values."""
        args: List[str] = []
        for widget in self.flag_widgets:
            option = widget.flag.long_option
            checkbox = widget.checkbox()
            if not option or not checkbox or not checkbox.isChecked():
                continue

            if widget.flag.takes_value:
                value_edit = widget.value_edit()
                if not value_edit:
                    continue
                value = value_edit.text().strip()
                if value:
                    expanded_value = os.path.expanduser(value)
                    # Expand user home before quoting so paths like ~/file resolve correctly.
                    quoted_value = shlex.quote(expanded_value)
                    args.append(f"{option} {quoted_value}")
            else:
                args.append(option)
        return args

    def input_position(self) -> QPointF:
        """Scene coordinates of the input port center."""
        return self.mapToScene(QPointF(self.rect().left(), self.rect().height() / 2.0))

    def output_position(self) -> QPointF:
        """Scene coordinates of the output port center."""
        return self.mapToScene(QPointF(self.rect().right(), self.rect().height() / 2.0))

    # ----------------
    # Qt event hooks
    # ----------------
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        """Notify the editor when the block has moved."""
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.editor.update_connections_for(self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.editor.try_snap_block(self)


class PaletteBlock(QGraphicsRectItem):
    """Template block shown in the palette; dragging spawns a canvas block."""

    def __init__(self, definition: BlockDefinition, editor: "WorkflowEditor"):
        super().__init__(0.0, 0.0, CanvasBlock.BASE_WIDTH, 90.0)
        self.definition = definition
        self.editor = editor

        self.setBrush(QColor("#E0E0E0"))
        self.setPen(QPen(Qt.black, 1, Qt.DotLine))
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

        title_font = QFont()
        title_font.setBold(True)

        command_font = QFont()
        command_font.setPointSize(8)

        self._title = QGraphicsTextItem(self.definition.title, self)
        self._title.setDefaultTextColor(Qt.black)
        self._title.setFont(title_font)
        self._title.setTextWidth(self.rect().width() - 16.0)
        self._title.setPos(8.0, 8.0)

        self._command = QGraphicsTextItem(self.definition.command, self)
        self._command.setDefaultTextColor(Qt.darkGray)
        self._command.setFont(command_font)
        self._command.setTextWidth(self.rect().width() - 16.0)
        self._command.setPos(8.0, 8.0 + self._title.boundingRect().height())

        self._dragged_block: Optional[CanvasBlock] = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragged_block = self.editor.spawn_canvas_block(self.definition)
            if self._dragged_block:
                self._dragged_block.setPos(
                    event.scenePos() - QPointF(self.rect().width() / 2.0, self.rect().height() / 2.0)
                )
                self._dragged_block.setSelected(True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragged_block:
            self._dragged_block.setPos(
                event.scenePos() - QPointF(self.rect().width() / 2.0, self.rect().height() / 2.0)
            )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._dragged_block = None


@dataclass
class Connection:
    """Represents a directional connection between two canvas blocks."""

    source: CanvasBlock
    target: CanvasBlock
    line_item: QGraphicsLineItem

    def update_geometry(self) -> None:
        """Refresh the line endpoints to match the current block positions."""
        start = self.source.output_position()
        end = self.target.input_position()
        self.line_item.setLine(start.x(), start.y(), end.x(), end.y())


class WorkflowEditor(QMainWindow):
    """Main window hosting the workflow editor scene."""

    def __init__(self, definitions: List[BlockDefinition], yaml_path: Path):
        super().__init__()
        self.definitions = definitions
        self.yaml_path = yaml_path
        self.base_dir = yaml_path.parent.resolve()

        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0.0, 0.0, 1600.0, 1200.0)
        self.view = QGraphicsView(self.scene)
        self.setCentralWidget(self.view)
        self.setWindowTitle("Workflow Editor")
        self.resize(900, 650)

        self.canvas_blocks: List[CanvasBlock] = []
        self.connections: List[Connection] = []

        self._install_execute_button()
        self._populate_palette()
        self._bootstrap_demo_chain()

    # ------------------------
    # UI initialization helpers
    # ------------------------
    def _install_execute_button(self) -> None:
        """Add the Execute button to the scene."""
        self.edsuite_label = QLabel("edsuite path:")
        label_proxy = self.scene.addWidget(self.edsuite_label)
        label_proxy.setPos(10.0, 10.0)

        self.edsuite_path_edit = QLineEdit("../edsuite")
        self.edsuite_path_edit.setFixedWidth(280)
        path_proxy = self.scene.addWidget(self.edsuite_path_edit)
        path_proxy.setPos(110.0, 8.0)

        self.execute_button = QPushButton("Execute")
        proxy = self.scene.addWidget(self.execute_button)
        proxy.setPos(10.0, 40.0)
        self.execute_button.clicked.connect(self.execute_workflow)  # type: ignore[arg-type]

        self.connect_button = QPushButton("Connect Selected")
        connect_proxy = self.scene.addWidget(self.connect_button)
        connect_proxy.setPos(110.0, 40.0)
        self.connect_button.clicked.connect(self.connect_selected_blocks)  # type: ignore[arg-type]

        self.disconnect_button = QPushButton("Disconnect Selected")
        disconnect_proxy = self.scene.addWidget(self.disconnect_button)
        disconnect_proxy.setPos(260.0, 40.0)
        self.disconnect_button.clicked.connect(self.disconnect_selected_blocks)  # type: ignore[arg-type]

        self.preview_checkbox = QCheckBox("Preview only (do not run)")
        preview_proxy = self.scene.addWidget(self.preview_checkbox)
        preview_proxy.setPos(420.0, 40.0)

        command_label = QLabel("Last command:")
        command_label_proxy = self.scene.addWidget(command_label)
        command_label_proxy.setPos(10.0, 70.0)

        self.command_display = QLineEdit()
        self.command_display.setReadOnly(True)
        self.command_display.setPlaceholderText("Built command will appear here")
        self.command_display.setFixedWidth(720)
        command_proxy = self.scene.addWidget(self.command_display)
        command_proxy.setPos(110.0, 68.0)

    def _populate_palette(self) -> None:
        """Create palette blocks laid out horizontally."""
        x_cursor = 10.0
        y_cursor = 110.0
        ordered_definitions = sorted(self.definitions, key=lambda d: d.title)
        for definition in ordered_definitions:
            palette_block = PaletteBlock(definition, self)
            self.scene.addItem(palette_block)
            palette_block.setPos(x_cursor, y_cursor)
            x_cursor += palette_block.rect().width() + 12.0

    def _bootstrap_demo_chain(self) -> None:
        """Pre-place all blocks and connect them sequentially."""
        if not self.definitions:
            return

        bootstrapped_defs = [d for d in self.definitions if d.include_in_bootstrap]
        ordered_defs = sorted(bootstrapped_defs, key=lambda d: d.title)
        x_cursor = 220.0
        y_position = 220.0
        spacing = 200.0
        previous_block: Optional[CanvasBlock] = None

        for definition in ordered_defs:
            block = self.spawn_canvas_block(definition)
            if not block:
                continue
            block.setPos(x_cursor, y_position)
            if previous_block:
                self.add_connection(previous_block, block)
            previous_block = block
            x_cursor += spacing

    # -----------------
    # Block management
    # -----------------
    def spawn_canvas_block(self, definition: BlockDefinition) -> Optional[CanvasBlock]:
        """Create a new canvas block instance based on the provided definition."""
        block = CanvasBlock(definition, self)
        self.scene.addItem(block)
        self.canvas_blocks.append(block)
        return block

    def add_connection(self, source: CanvasBlock, target: CanvasBlock) -> None:
        """Create or refresh a directional connection between blocks."""
        if source == target:
            return
        existing = self._find_connection(source, target)
        if existing:
            existing.update_geometry()
            return

        self._remove_outgoing_connections(source)
        self._remove_incoming_connections(target)

        line = QGraphicsLineItem()
        line.setPen(QPen(Qt.darkGray, 2))
        line.setFlag(QGraphicsItem.ItemIsSelectable, True)
        line.setZValue(-1.0)
        self.scene.addItem(line)
        connection = Connection(source=source, target=target, line_item=line)
        connection.update_geometry()
        self.connections.append(connection)

    def remove_connections_involving(self, block: CanvasBlock) -> None:
        """Remove any connections where the provided block participates."""
        to_remove = [c for c in self.connections if c.source == block or c.target == block]
        for connection in to_remove:
            self._remove_connection(connection)
        self.connections = [c for c in self.connections if c not in to_remove]

    def remove_canvas_block(self, block: CanvasBlock) -> None:
        """Remove a canvas block and any connections linked to it."""
        self.remove_connections_involving(block)
        if block in self.canvas_blocks:
            self.canvas_blocks.remove(block)
        if block.scene():
            self.scene.removeItem(block)

    def delete_selected_canvas_blocks(self) -> bool:
        """Delete all selected canvas blocks. Returns True if any were removed."""
        removed = False
        for item in list(self.scene.selectedItems()):
            if isinstance(item, CanvasBlock):
                self.remove_canvas_block(item)
                removed = True
        return removed

    def delete_selected_connections(self) -> bool:
        """Delete all selected connections."""
        removed = False
        for connection in list(self.connections):
            if connection.line_item.isSelected():
                self._remove_connection(connection)
                self.connections.remove(connection)
                removed = True
        return removed

    def connect_selected_blocks(self) -> None:
        """Connect two selected blocks (left-most becomes source)."""
        blocks = self._selected_canvas_blocks()
        if len(blocks) != 2:
            print("[workflow_editor] Select exactly two blocks to connect.")
            return
        a, b = blocks
        source, target = (a, b) if a.scenePos().x() <= b.scenePos().x() else (b, a)
        self.add_connection(source, target)

    def disconnect_selected_blocks(self) -> None:
        """Remove any connections between selected blocks."""
        blocks = self._selected_canvas_blocks()
        if len(blocks) != 2:
            print("[workflow_editor] Select exactly two blocks to disconnect.")
            return
        removed_any = False
        for source, target in ((blocks[0], blocks[1]), (blocks[1], blocks[0])):
            connection = self._find_connection(source, target)
            if connection:
                self._remove_connection(connection)
                self.connections.remove(connection)
                removed_any = True
        if not removed_any:
            print("[workflow_editor] No connection found between selected blocks.")

    def _selected_canvas_blocks(self) -> List[CanvasBlock]:
        """Return all selected canvas blocks in the scene."""
        return [item for item in self.scene.selectedItems() if isinstance(item, CanvasBlock)]

    def _find_connection(self, source: CanvasBlock, target: CanvasBlock) -> Optional[Connection]:
        """Return the connection from source to target if present."""
        for connection in self.connections:
            if connection.source == source and connection.target == target:
                return connection
        return None

    def _remove_outgoing_connections(self, source: CanvasBlock) -> None:
        """Ensure only one outgoing connection per source block."""
        for connection in list(self.connections):
            if connection.source == source:
                self._remove_connection(connection)
                self.connections.remove(connection)

    def _remove_incoming_connections(self, target: CanvasBlock) -> None:
        """Ensure only one incoming connection per target block."""
        for connection in list(self.connections):
            if connection.target == target:
                self._remove_connection(connection)
                self.connections.remove(connection)

    def _remove_connection(self, connection: Connection) -> None:
        """Detach a connection from the scene."""
        if connection.line_item.scene():
            self.scene.removeItem(connection.line_item)

    def _resolve_edsuite_path(self) -> Optional[Path]:
        """Resolve the edsuite path from the UI field."""
        text = self.edsuite_path_edit.text().strip() if hasattr(self, "edsuite_path_edit") else ""
        if not text:
            text = "."
        candidate = Path(text)
        try:
            if not candidate.is_absolute():
                candidate = (self.base_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
        except OSError as exc:
            print(f"[workflow_editor] Invalid edsuite path '{text}': {exc}")
            return None

        if not candidate.is_dir():
            print(f"[workflow_editor] edsuite path does not exist: {candidate}")
            return None
        return candidate

    def _update_last_command_display(self, command: str) -> None:
        """Show the most recently built command in the UI."""
        if hasattr(self, "command_display"):
            self.command_display.setText(command)
            self.command_display.setCursorPosition(0)

    # --------------------------
    # Connection / snap handling
    # --------------------------
    def update_connections_for(self, block: CanvasBlock) -> None:
        """Update geometry for all connections touching the given block."""
        for connection in self.connections:
            if connection.source == block or connection.target == block:
                connection.update_geometry()

    def try_snap_block(self, block: CanvasBlock) -> None:
        """Snap the moving block to nearby ports and create connections."""
        snap_radius = 20.0
        for other in self.canvas_blocks:
            if other is block:
                continue

            output_to_input = self._distance(block.output_position(), other.input_position())
            if output_to_input <= snap_radius:
                self._align_block(block, other, align_output=True)
                self.add_connection(block, other)
                return

            input_to_output = self._distance(block.input_position(), other.output_position())
            if input_to_output <= snap_radius:
                self._align_block(other, block, align_output=True)
                self.add_connection(other, block)
                return

    def _align_block(self, source: CanvasBlock, target: CanvasBlock, align_output: bool) -> None:
        """Align two blocks so their ports overlap."""
        if align_output:
            source_pos = source.output_position()
            target_pos = target.input_position()
        else:
            source_pos = source.input_position()
            target_pos = target.output_position()

        delta = target_pos - source_pos
        source.setPos(source.pos() + delta)

    @staticmethod
    def _distance(a: QPointF, b: QPointF) -> float:
        """Return Euclidean distance between two points."""
        return math.hypot(a.x() - b.x(), a.y() - b.y())

    # -----------------------
    # Command-line execution
    # -----------------------
    def ordered_blocks(self) -> List[CanvasBlock]:
        """
        Return blocks ordered by the current connections.

        This implementation assumes a simple chain (Phase 1 requirement) and
        follows at most one outgoing connection per block.
        """
        if not self.canvas_blocks:
            return []

        outgoing: Dict[CanvasBlock, CanvasBlock] = {}
        incoming_count: Dict[CanvasBlock, int] = {block: 0 for block in self.canvas_blocks}
        for connection in self.connections:
            outgoing[connection.source] = connection.target
            incoming_count[connection.target] = incoming_count.get(connection.target, 0) + 1
            incoming_count.setdefault(connection.source, 0)

        starts = [block for block, count in incoming_count.items() if count == 0 and block in outgoing]
        visited: List[CanvasBlock] = []

        def walk(start_block: CanvasBlock) -> None:
            block = start_block
            while block and block not in visited:
                visited.append(block)
                block = outgoing.get(block)

        if starts:
            for start in starts:
                walk(start)
        else:
            visited.extend(self.canvas_blocks)

        for block in self.canvas_blocks:
            if block not in visited:
                visited.append(block)
        return visited

    def build_command_string(self) -> str:
        """Generate the pipeline command string from connected blocks."""
        segments: List[str] = []
        for block in self.ordered_blocks():
            if not block.definition.command:
                continue
            parts = [block.definition.command]
            parts.extend(block.flag_arguments())
            segment = " ".join(part for part in parts if part)
            if segment:
                segments.append(segment)
        return " | ".join(segments)

    def execute_workflow(self) -> None:
        """Build the command string and execute the chained_app script."""
        command_string = self.build_command_string()
        if not command_string:
            print("[workflow_editor] Nothing to execute.")
            return

        self._update_last_command_display(command_string)

        edsuite_root = self._resolve_edsuite_path()
        if not edsuite_root:
            return

        if getattr(self, "preview_checkbox", None) and self.preview_checkbox.isChecked():
            print(
                "[workflow_editor] Preview mode enabled; command not executed. "
                "Run the following in a terminal:\n"
                f"{command_string}"
            )
            QMessageBox.information(
                self,
                "Preview mode",
                f"Command built but not executed.\n\nRun this in a terminal:\n{command_string}",
            )
            return

        env = os.environ.copy()
        bin_dir = edsuite_root / ".venv"
        if os.name == "nt":
            bin_dir = bin_dir / "Scripts"
        else:
            bin_dir = bin_dir / "bin"
        if bin_dir.exists():
            existing_path = env.get("PATH", "")
            env["PATH"] = f"{bin_dir}{os.pathsep}{existing_path}"
        else:
            print(f"[workflow_editor] Warning: expected virtualenv at {bin_dir} not found.")

        print(f"[workflow_editor] Executing pipeline in {edsuite_root}: {command_string}")
        try:
            subprocess.run(
                command_string,
                shell=True,
                cwd=str(edsuite_root),
                env=env,
                check=False,
                executable="/bin/bash" if os.name != "nt" else None,
            )
        except Exception as exc:  # noqa: BLE001 - log unexpected failures
            print(f"[workflow_editor] Failed to execute pipeline: {exc}")

    def keyPressEvent(self, event):
        """Handle global key events for the editor window."""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            handled = False
            if self.delete_selected_canvas_blocks():
                handled = True
            if self.delete_selected_connections():
                handled = True
            if handled:
                event.accept()
                return
        super().keyPressEvent(event)


def build_app(yaml_path: Path) -> QApplication:
    """Create the QApplication and workflow editor window."""
    app = QApplication.instance() or QApplication(sys.argv)
    definitions = load_block_definitions(yaml_path)
    editor = WorkflowEditor(definitions, yaml_path)
    editor.show()
    return app


def main() -> int:
    """Entry point for the workflow editor."""
    yaml_path = Path(__file__).with_name("blocks.yaml")
    app = QApplication.instance() or QApplication(sys.argv)
    definitions = load_block_definitions(yaml_path)
    editor = WorkflowEditor(definitions, yaml_path)
    editor.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
