# -*- coding: utf-8 -*-
"""自定义界面组件：趋势微折线图、多品牌外设电量卡片与可选桌面悬浮窗。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ..models import DeviceState
from .icons import (
    battery_color,
    paint_bolt_glyph,
    paint_device_glyph,
    paint_keyboard_glyph,
    paint_mouse_glyph,
)


def paint_glyph_by_kind(painter: QPainter, rect: QRectF, kind: str, color: QColor) -> None:
    """按设备类型绘制对应的矢量图标。"""
    if kind == "mouse":
        paint_mouse_glyph(painter, rect, color)
    elif kind == "keyboard":
        paint_keyboard_glyph(painter, rect, color)
    else:
        paint_device_glyph(painter, rect, color)


class GlyphBadge(QWidget):
    """矢量图标徽章控件。"""

    def __init__(self, kind: str = "mouse", box_size: int = 40, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._color = QColor("#22C55E")
        self._bg_color = QColor("#162235")
        self.setFixedSize(box_size, box_size)

    def set_kind(self, kind: str) -> None:
        if self._kind != kind:
            self._kind = kind
            self.update()

    def set_accent(self, color: QColor, bg_color: QColor | None = None) -> None:
        self._color = color
        if bg_color is not None:
            self._bg_color = bg_color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        if self._bg_color.alpha() > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg_color)
            painter.drawRoundedRect(rect, 11, 11)

        pad = self.width() * 0.20
        icon_rect = QRectF(pad, pad, self.width() - pad * 2, self.height() - pad * 2)
        paint_glyph_by_kind(painter, icon_rect, self._kind, self._color)
        painter.end()


class BatteryBarWidget(QWidget):
    """圆角渐变动效电量进度条。"""

    def __init__(self, height: int = 8, parent=None) -> None:
        super().__init__(parent)
        self._value = 0
        self._has_value = False
        self._color = QColor("#22C55E")
        self.setFixedHeight(height)

    def set_state(self, battery: int | None, color: QColor) -> None:
        self._has_value = battery is not None
        self._value = max(0, min(100, int(battery))) if battery is not None else 0
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        radius = rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1E293B"))
        painter.drawRoundedRect(rect, radius, radius)

        if self._has_value and self._value > 0:
            fill_w = max(rect.height(), rect.width() * (self._value / 100.0))
            fill_rect = QRectF(0, 0, min(rect.width(), fill_w), rect.height())
            grad = QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
            lighter = QColor(self._color)
            lighter.setAlpha(215)
            grad.setColorAt(0.0, lighter)
            grad.setColorAt(1.0, self._color)
            painter.setBrush(grad)
            painter.drawRoundedRect(fill_rect, radius, radius)

        painter.end()


class SparklineWidget(QWidget):
    """近期电量变化微折线图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list[int] = []
        self._color = QColor("#22C55E")
        self.setFixedHeight(26)

    def set_history(self, history: list[list[float]], color: QColor) -> None:
        self._points = [max(0, min(100, int(item[1]))) for item in history[-30:]]
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        pad_y = 4.0

        if len(self._points) < 2:
            pen = QPen(QColor("#263043"), 1.2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(0, h * 0.6), QPointF(w, h * 0.6))
            painter.end()
            return

        vals = self._points
        min_v = min(vals)
        max_v = max(vals)
        span = max(10.0, float(max_v - min_v))
        base_v = max(0.0, float(min_v) - span * 0.15)
        top_v = min(100.0, base_v + span * 1.3)
        v_range = max(5.0, top_v - base_v)

        coords: list[QPointF] = []
        step_x = w / max(1, len(vals) - 1)
        for idx, val in enumerate(vals):
            x = idx * step_x
            norm = (val - base_v) / v_range
            y = h - pad_y - norm * (h - pad_y * 2)
            coords.append(QPointF(x, y))

        line_path = QPainterPath(coords[0])
        for pt in coords[1:]:
            line_path.lineTo(pt)

        area_path = QPainterPath(line_path)
        area_path.lineTo(coords[-1].x(), h)
        area_path.lineTo(coords[0].x(), h)
        area_path.closeSubpath()

        fill_grad = QLinearGradient(0, 0, 0, h)
        c_top = QColor(self._color)
        c_top.setAlpha(65)
        c_bot = QColor(self._color)
        c_bot.setAlpha(0)
        fill_grad.setColorAt(0.0, c_top)
        fill_grad.setColorAt(1.0, c_bot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill_grad)
        painter.drawPath(area_path)

        painter.setPen(QPen(self._color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line_path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(coords[-1], 2.6, 2.6)
        painter.end()


class DeviceCard(QFrame):
    """单个外设的高质感暗色电量展示卡片。"""

    def __init__(self, kind: str = "mouse", title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("DeviceCard")
        self.setStyleSheet(
            """
            #DeviceCard {
                background-color: #131B2B;
                border: 1px solid #222E44;
                border-radius: 14px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.badge = GlyphBadge(kind, box_size=40, parent=self)
        top_row.addWidget(self.badge)

        name_col = QVBoxLayout()
        name_col.setSpacing(3)

        self.name_label = QLabel(title)
        self.name_label.setStyleSheet(
            "color: #F1F5F9; font-size: 13px; font-weight: 600; background: transparent;"
        )
        name_col.addWidget(self.name_label)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(6)
        self.status_pill = QLabel("检测中")
        self.status_pill.setStyleSheet(
            "color: #94A3B8; background-color: #1E293B; border-radius: 6px;"
            "padding: 2px 7px; font-size: 11px; font-weight: 500;"
        )
        self.conn_pill = QLabel("2.4G")
        self.conn_pill.setStyleSheet(
            "color: #94A3B8; background-color: #1A2436; border-radius: 6px;"
            "padding: 2px 6px; font-size: 10px; font-weight: 500;"
        )
        pill_row.addWidget(self.status_pill)
        pill_row.addWidget(self.conn_pill)
        pill_row.addStretch(1)
        name_col.addLayout(pill_row)
        top_row.addLayout(name_col, 1)

        self.pct_label = QLabel("--%")
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pct_label.setStyleSheet(
            "color: #E2E8F0; font-size: 22px; font-weight: 700; background: transparent;"
        )
        top_row.addWidget(self.pct_label)
        root.addLayout(top_row)

        self.progress = BatteryBarWidget(height=7, parent=self)
        root.addWidget(self.progress)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.detail_left = QLabel("等待检测...")
        self.detail_left.setStyleSheet("color: #94A3B8; font-size: 11px; background: transparent;")
        self.detail_right = QLabel("--:--:--")
        self.detail_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.detail_right.setStyleSheet("color: #64748B; font-size: 11px; background: transparent;")
        meta_row.addWidget(self.detail_left, 1)
        meta_row.addWidget(self.detail_right)
        root.addLayout(meta_row)

        self.sparkline = SparklineWidget(parent=self)
        root.addWidget(self.sparkline)

    def update_state(self, state: DeviceState, display_name: str) -> None:
        """刷新卡片所有显示字段。"""
        self.kind = state.kind
        self.badge.set_kind(state.kind)
        self.name_label.setText(display_name)
        color = battery_color(state)
        hex_color = color.name()

        bg_tint = QColor(color)
        bg_tint.setAlpha(30)
        self.badge.set_accent(color, bg_tint)

        if state.battery is not None:
            prefix = "⚡ " if state.charging is True else ""
            self.pct_label.setText(f"{prefix}{state.battery}%")
        else:
            self.pct_label.setText("--%")
        self.pct_label.setStyleSheet(
            f"color: {hex_color}; font-size: 22px; font-weight: 700; background: transparent;"
        )

        pill_bg = QColor(color)
        self.status_pill.setText(state.status_label)
        self.status_pill.setStyleSheet(
            f"color: {hex_color}; background-color: rgba({pill_bg.red()}, {pill_bg.green()}, {pill_bg.blue()}, 36);"
            "border-radius: 6px; padding: 2px 7px; font-size: 11px; font-weight: 600;"
        )

        conn_text = state.protocol or state.connection_type or "无线"
        self.conn_pill.setText(conn_text)
        self.progress.set_state(state.battery, color)

        parts: list[str] = []
        if state.voltage_mv:
            parts.append(f"电压 {state.voltage_mv / 1000:.3f} V ({state.voltage_mv} mV)")
        elif state.kind == "keyboard" and state.status_flag is not None:
            parts.append(f"状态码 0x{state.status_flag:02X}")

        if state.status == "disconnected":
            parts = [state.last_error or "未检测到设备"]
        elif state.status == "sleeping" and state.battery is None:
            parts = [state.last_error or "设备休眠中，唤醒后自动更新"]
        elif not parts:
            if state.vid:
                parts = [f"VID:PID {state.vid:04X}:{state.pid:04X}"]
            else:
                parts = [f"{state.connection_type}实时电量"]

        self.detail_left.setText(" · ".join(parts))
        self.detail_right.setText(f"更新 {state.formatted_update_time()}")
        self.sparkline.set_history(state.history, color)


class FloatingBatteryWidget(QWidget):
    """可选的极简桌面悬浮药丸条（默认关闭，支持展示主设备电量）。"""

    open_flyout_requested = Signal()
    refresh_requested = Signal()
    hide_requested = Signal()
    toggle_top_requested = Signal(bool)
    position_changed = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self._always_on_top = True
        self._devices: list[DeviceState] = []

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_window_flags(True)
        self.setFixedSize(218, 42)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("左键拖动位置 · 双击打开电量面板 · 右键打开菜单")

    def _apply_window_flags(self, on_top: bool) -> None:
        self._always_on_top = on_top
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def apply_settings(self, always_on_top: bool, opacity: float) -> None:
        if always_on_top != self._always_on_top:
            self._apply_window_flags(always_on_top)
        self.setWindowOpacity(max(0.45, min(1.0, opacity)))

    def update_states(self, devices: list[DeviceState]) -> None:
        self._devices = list(devices[:2])
        target_w = 122 if len(self._devices) <= 1 else 218
        if self.width() != target_w:
            self.setFixedWidth(target_w)
        self.update()

    def _draw_slot(self, painter: QPainter, start_x: float, st: DeviceState | None) -> None:
        color = battery_color(st)
        kind = st.kind if st else "mouse"
        paint_glyph_by_kind(painter, QRectF(start_x, 11, 18, 20), kind, color)

        text = f"{st.battery}%" if (st and st.battery is not None) else "--%"
        font = painter.font()
        font.setFamily("Segoe UI")
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#F1F5F9"))
        painter.drawText(
            QRectF(start_x + 22, 4, 52, 24),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        if st and st.charging:
            paint_bolt_glyph(painter, QRectF(start_x + 64, 10, 10, 12), QColor("#38BDF8"))

        pct = 0.0 if (not st or st.battery is None) else st.battery / 100.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1E293B"))
        painter.drawRoundedRect(QRectF(start_x + 22, 29, 54, 4), 2, 2)
        if pct > 0:
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(start_x + 22, 29, max(4.0, 54.0 * pct), 4), 2, 2)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(QPen(QColor("#293548"), 1.2))
        painter.setBrush(QColor(15, 23, 42, 235))
        painter.drawRoundedRect(rect, 20, 20)

        first = self._devices[0] if len(self._devices) >= 1 else None
        self._draw_slot(painter, 12, first)

        if len(self._devices) >= 2:
            painter.setPen(QPen(QColor("#293548"), 1.0))
            painter.drawLine(QPointF(108, 10), QPointF(108, 32))
            self._draw_slot(painter, 118, self._devices[1])

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            pos = self.pos()
            self.position_changed.emit(pos.x(), pos.y())
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_flyout_requested.emit()
            event.accept()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        act_open = menu.addAction("打开电量主面板")
        act_refresh = menu.addAction("立即刷新电量")
        menu.addSeparator()
        act_top = menu.addAction("窗口置顶")
        act_top.setCheckable(True)
        act_top.setChecked(self._always_on_top)
        act_hide = menu.addAction("隐藏桌面悬浮窗")

        chosen = menu.exec(event.globalPos())
        if chosen == act_open:
            self.open_flyout_requested.emit()
        elif chosen == act_refresh:
            self.refresh_requested.emit()
        elif chosen == act_top:
            self.toggle_top_requested.emit(act_top.isChecked())
        elif chosen == act_hide:
            self.hide_requested.emit()
