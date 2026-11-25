# -*- coding: utf-8 -*-
"""基于 QPainter 的矢量图标与动态多设备托盘图标绘制模块。"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..models import DeviceState


def battery_color(state: DeviceState | None) -> QColor:
    """根据设备在线状态、充电状态与电量返回高对比度主题色。"""
    if state is None or state.battery is None or state.status == "disconnected":
        return QColor("#94A3B8")
    if state.charging is True:
        return QColor("#38BDF8")
    if state.status == "sleeping":
        return QColor("#94A3B8")
    if state.battery >= 50:
        return QColor("#22C55E")
    if state.battery >= 20:
        return QColor("#F59E0B")
    return QColor("#EF4444")


def paint_mouse_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """在指定矩形区域内矢量绘制鼠标图标。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, max(1.5, rect.width() * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    body = QRectF(x + w * 0.22, y + h * 0.08, w * 0.56, h * 0.84)
    painter.drawRoundedRect(body, w * 0.28, w * 0.28)
    cx = x + w * 0.5
    painter.drawLine(QPointF(cx, y + h * 0.22), QPointF(cx, y + h * 0.40))
    painter.restore()


def paint_keyboard_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """在指定矩形区域内矢量绘制键盘图标。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, max(1.4, rect.width() * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    body = QRectF(x + w * 0.08, y + h * 0.22, w * 0.84, h * 0.56)
    painter.drawRoundedRect(body, w * 0.12, w * 0.12)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    dot_w = w * 0.10
    dot_h = h * 0.08
    for row_y in (y + h * 0.34, y + h * 0.48):
        for col_x in (0.20, 0.36, 0.52, 0.68):
            painter.drawRoundedRect(QRectF(x + w * col_x, row_y, dot_w, dot_h), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(x + w * 0.26, y + h * 0.62, w * 0.48, dot_h), 1.0, 1.0)
    painter.restore()


def paint_device_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """绘制通用无线外设图标（蓝牙/无线电波徽标）。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, max(1.5, rect.width() * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    # 中心无线圆点 + 两道外扩弧线
    painter.drawArc(QRectF(x + w * 0.12, y + h * 0.12, w * 0.76, h * 0.76), 45 * 16, 90 * 16)
    painter.drawArc(QRectF(x + w * 0.26, y + h * 0.26, w * 0.48, h * 0.48), 45 * 16, 90 * 16)
    painter.drawArc(QRectF(x + w * 0.12, y + h * 0.12, w * 0.76, h * 0.76), 225 * 16, 90 * 16)
    painter.drawArc(QRectF(x + w * 0.26, y + h * 0.26, w * 0.48, h * 0.48), 225 * 16, 90 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(x + w * 0.5, y + h * 0.5), w * 0.11, h * 0.11)
    painter.restore()


def paint_bolt_glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """绘制充电闪电符号。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    w, h = rect.width(), rect.height()
    x, y = rect.left(), rect.top()
    path = QPainterPath()
    path.moveTo(x + w * 0.58, y + h * 0.05)
    path.lineTo(x + w * 0.22, y + h * 0.54)
    path.lineTo(x + w * 0.48, y + h * 0.54)
    path.lineTo(x + w * 0.38, y + h * 0.95)
    path.lineTo(x + w * 0.78, y + h * 0.44)
    path.lineTo(x + w * 0.52, y + h * 0.44)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def _format_tray_num(state: DeviceState | None) -> str:
    """格式化托盘紧凑数字文本。"""
    if state is None or state.battery is None:
        return "--"
    return str(max(0, min(100, int(state.battery))))


def _draw_kind_marker(painter: QPainter, x: float, y: float, kind: str, color: QColor) -> None:
    """在托盘左侧绘制极简设备形状标识点（鼠标圆点/键盘方点/其他菱形）。"""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    if kind == "mouse":
        painter.drawEllipse(QRectF(x, y, 7, 7))
    elif kind == "keyboard":
        painter.drawRoundedRect(QRectF(x, y, 7, 7), 2.0, 2.0)
    else:
        path = QPainterPath()
        cx, cy = x + 3.5, y + 3.5
        path.moveTo(cx, y)
        path.lineTo(x + 7, cy)
        path.lineTo(cx, y + 7)
        path.lineTo(x, cy)
        path.closeSubpath()
        painter.drawPath(path)
    painter.restore()


def create_tray_icon(
    devices: list[DeviceState],
    style: str = "dual_number",
) -> QIcon:
    """绘制 64x64 高清系统托盘动态图标，自适应 0/1/2+ 台无线外设。"""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    bg_rect = QRectF(2, 2, size - 4, size - 4)
    painter.setPen(QPen(QColor("#334155"), 2.0))
    painter.setBrush(QColor("#0F172A"))
    painter.drawRoundedRect(bg_rect, 12, 12)

    if not devices:
        font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#94A3B8"))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, "--")
        painter.end()
        return QIcon(pixmap)

    if len(devices) == 1:
        st = devices[0]
        color = battery_color(st)
        if style == "dual_bar":
            track = QRectF(10, 24, 44, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1E293B"))
            painter.drawRoundedRect(track, 6, 6)
            pct = 0.0 if st.battery is None else max(0, min(100, st.battery)) / 100.0
            if pct > 0:
                fill_w = max(10.0, track.width() * pct)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(track.left(), track.top(), fill_w, track.height()), 6, 6)
        else:
            font = QFont("Segoe UI", 25, QFont.Weight.Bold)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(QRectF(4, 10, 56, 44), Qt.AlignmentFlag.AlignCenter, _format_tray_num(st))
        painter.end()
        return QIcon(pixmap)

    first, second = devices[0], devices[1]
    c1, c2 = battery_color(first), battery_color(second)

    if style == "dual_bar":
        for idx, (st, color) in enumerate(((first, c1), (second, c2))):
            row_y = 11.0 if idx == 0 else 37.0
            _draw_kind_marker(painter, 7, row_y + 4, st.kind, color)

            track = QRectF(18, row_y + 1, 38, 13)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1E293B"))
            painter.drawRoundedRect(track, 5, 5)

            pct = 0.0 if st.battery is None else max(0, min(100, st.battery)) / 100.0
            if pct > 0:
                fill_w = max(8.0, track.width() * pct)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(track.left(), track.top(), fill_w, track.height()), 5, 5)
    else:
        _draw_kind_marker(painter, 7, 15, first.kind, c1)
        _draw_kind_marker(painter, 7, 43, second.kind, c2)

        font = QFont("Segoe UI", 21, QFont.Weight.Bold)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        painter.setFont(font)

        painter.setPen(c1)
        painter.drawText(QRectF(15, 3, 45, 29), Qt.AlignmentFlag.AlignCenter, _format_tray_num(first))

        painter.setPen(QPen(QColor("#1E293B"), 1.5))
        painter.drawLine(QPointF(10, 32), QPointF(54, 32))

        painter.setPen(c2)
        painter.drawText(QRectF(15, 32, 45, 29), Qt.AlignmentFlag.AlignCenter, _format_tray_num(second))

    painter.end()
    return QIcon(pixmap)


def create_app_icon() -> QIcon:
    """绘制应用主图标（电池能量徽章）。"""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#38BDF8"), 2.2))
    painter.setBrush(QColor("#0F172A"))
    painter.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    paint_bolt_glyph(painter, QRectF(16, 12, 32, 40), QColor("#22C55E"))
    painter.end()
    return QIcon(pixmap)
