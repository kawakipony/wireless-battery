# -*- coding: utf-8 -*-
"""Windows 11 风格右下角托盘飞出主面板（支持动态多设备列表与设置页）。"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, is_autostart_enabled
from ..models import DeviceState
from .widgets import DeviceCard

PANEL_STYLE = """
#FlyoutContainer {
    background-color: #0B1220;
    border: 1px solid #24324B;
    border-radius: 16px;
}
QLabel {
    color: #E2E8F0;
    background: transparent;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 5px;
    margin: 2px 0;
}
QScrollBar::handle:vertical {
    background: #2D3D5A;
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QPushButton#HeaderBtn {
    background-color: #162033;
    color: #CBD5E1;
    border: 1px solid #26344D;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton#HeaderBtn:hover {
    background-color: #1E2D47;
    color: #FFFFFF;
}
QPushButton#PrimaryBtn {
    background-color: #0284C7;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#PrimaryBtn:hover {
    background-color: #0EA5E9;
}
QComboBox, QLineEdit {
    background-color: #131B2B;
    color: #F1F5F9;
    border: 1px solid #2A3954;
    border-radius: 8px;
    padding: 5px 8px;
    font-size: 12px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #131B2B;
    color: #F1F5F9;
    selection-background-color: #0284C7;
    border: 1px solid #2A3954;
}
QCheckBox {
    color: #E2E8F0;
    font-size: 12px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #3B4E6E;
    background-color: #131B2B;
}
QCheckBox::indicator:checked {
    background-color: #0EA5E9;
    border-color: #0EA5E9;
}
"""


class BatteryFlyout(QWidget):
    """右下角托盘点击弹出的无边框暗色面板。"""

    refresh_requested = Signal()
    settings_saved = Signal(object, bool)  # (AppConfig, autostart_enabled)
    clear_disconnected_requested = Signal()
    exit_requested = Signal()

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._devices: list[DeviceState] = []
        self._cards_by_key: dict[str, DeviceCard] = {}
        self._alias_inputs: dict[str, QLineEdit] = {}
        self.last_hidden_ts: float = 0.0
        self._suppress_auto_hide = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(374)
        self.setStyleSheet(PANEL_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        self.container = QFrame(self)
        self.container.setObjectName("FlyoutContainer")
        outer.addWidget(self.container)

        root = QVBoxLayout(self.container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 顶部标题栏
        header = QHBoxLayout()
        header.setSpacing(6)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.title_label = QLabel("无线外设电量")
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #F8FAFC;")
        self.subtitle_label = QLabel("2.4G & 蓝牙实时监测")
        self.subtitle_label.setStyleSheet("font-size: 11px; color: #64748B;")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header.addLayout(title_col, 1)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("HeaderBtn")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.btn_refresh)

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("HeaderBtn")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self._toggle_settings_page)
        header.addWidget(self.btn_settings)

        self.btn_hide = QPushButton("收起")
        self.btn_hide.setObjectName("HeaderBtn")
        self.btn_hide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hide.clicked.connect(self.hide_panel)
        header.addWidget(self.btn_hide)
        root.addLayout(header)

        # 主内容栈：0=电量总览，1=设置页
        self.stack = QStackedWidget(self.container)
        root.addWidget(self.stack)

        # --- 页面 0：动态多设备电量总览 ---
        overview_page = QWidget()
        ov_layout = QVBoxLayout(overview_page)
        ov_layout.setContentsMargins(0, 2, 0, 0)
        ov_layout.setSpacing(10)

        self.scroll_area = QScrollArea(overview_page)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.cards_host = QWidget()
        self.cards_host.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 2, 0)
        self.cards_layout.setSpacing(10)

        self.empty_card = self._build_empty_card()
        self.cards_layout.addWidget(self.empty_card)
        self.cards_layout.addStretch(1)

        self.scroll_area.setWidget(self.cards_host)
        ov_layout.addWidget(self.scroll_area)

        footer = QHBoxLayout()
        self.footer_hint = QLabel("点击托盘图标可随时收起或查看")
        self.footer_hint.setStyleSheet("font-size: 11px; color: #64748B;")
        footer.addWidget(self.footer_hint, 1)

        self.btn_quit = QPushButton("退出程序")
        self.btn_quit.setObjectName("HeaderBtn")
        self.btn_quit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quit.clicked.connect(self.exit_requested.emit)
        footer.addWidget(self.btn_quit)
        ov_layout.addLayout(footer)
        self.stack.addWidget(overview_page)

        # --- 页面 1：设置页 ---
        settings_page = QWidget()
        st_layout = QVBoxLayout(settings_page)
        st_layout.setContentsMargins(0, 2, 0, 0)
        st_layout.setSpacing(9)

        self.cmb_interval = self._add_combo_row(
            st_layout,
            "后台轮询间隔",
            [("1 分钟", 60), ("2 分钟（推荐）", 120), ("5 分钟", 300), ("10 分钟", 600)],
        )
        self.cmb_tray_style = self._add_combo_row(
            st_layout,
            "托盘图标样式",
            [("双行电量数字", "dual_number"), ("双色电量条", "dual_bar")],
        )
        self.cmb_threshold = self._add_combo_row(
            st_layout,
            "低电量提醒阈值",
            [("低于 10%", 10), ("低于 15%", 15), ("低于 20%", 20), ("低于 30%", 30)],
        )

        self.chk_low_notify = QCheckBox("开启低电量系统托盘通知")
        self.chk_autostart = QCheckBox("开机自动启动（静默驻留托盘）")
        self.chk_floating = QCheckBox("同时显示桌面悬浮药丸条")
        self.chk_float_top = QCheckBox("桌面悬浮条始终置顶")
        st_layout.addWidget(self.chk_low_notify)
        st_layout.addWidget(self.chk_autostart)
        st_layout.addWidget(self.chk_floating)
        st_layout.addWidget(self.chk_float_top)

        alias_title = QLabel("已发现设备显示名称（留空则使用硬件原名）")
        alias_title.setStyleSheet("font-size: 11px; color: #94A3B8; padding-top: 2px;")
        st_layout.addWidget(alias_title)

        self.alias_container = QVBoxLayout()
        self.alias_container.setSpacing(6)
        st_layout.addLayout(self.alias_container)

        action_row = QHBoxLayout()
        self.btn_clear_history = QPushButton("清理已断开设备")
        self.btn_clear_history.setObjectName("HeaderBtn")
        self.btn_clear_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_history.clicked.connect(self._on_clear_disconnected)
        action_row.addWidget(self.btn_clear_history)
        action_row.addStretch(1)

        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("PrimaryBtn")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save_clicked)
        action_row.addWidget(btn_save)
        st_layout.addLayout(action_row)

        self.save_status_label = QLabel("")
        self.save_status_label.setStyleSheet("font-size: 11px; color: #22C55E;")
        st_layout.addWidget(self.save_status_label)

        self.stack.addWidget(settings_page)
        self.sync_settings_ui(config)

    @staticmethod
    def _build_empty_card() -> QFrame:
        card = QFrame()
        card.setObjectName("DeviceCard")
        card.setStyleSheet(
            """
            #DeviceCard {
                background-color: #131B2B;
                border: 1px solid #222E44;
                border-radius: 14px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        lbl_title = QLabel("暂未检测到兼容的无线外设")
        lbl_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #F1F5F9;")
        lbl_desc = QLabel(
            "请确认 2.4G 接收器已插好或蓝牙外设已连接。\n"
            "当前支持：国产 Compx (VGN/VXE/ATK/迈从/狼蛛等)、\n"
            "罗技 HID++、雷蛇无线外设，以及所有 Windows 蓝牙外设。"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 11px; color: #94A3B8; line-height: 1.4;")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_desc)
        return card

    @staticmethod
    def _add_combo_row(
        parent_layout: QVBoxLayout, label_text: str, items: list[tuple[str, object]]
    ) -> QComboBox:
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 12px; color: #CBD5E1;")
        cmb = QComboBox()
        for text, data in items:
            cmb.addItem(text, data)
        cmb.setFixedWidth(165)
        row.addWidget(lbl, 1)
        row.addWidget(cmb)
        parent_layout.addLayout(row)
        return cmb

    @staticmethod
    def _select_combo_data(cmb: QComboBox, target_data) -> None:
        idx = cmb.findData(target_data)
        if idx >= 0:
            cmb.setCurrentIndex(idx)

    def _rebuild_alias_inputs(self) -> None:
        while self.alias_container.count():
            item = self.alias_container.takeAt(0)
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
            elif item.widget():
                item.widget().deleteLater()

        self._alias_inputs.clear()
        if not self._devices:
            lbl = QLabel("暂无已发现设备")
            lbl.setStyleSheet("font-size: 11px; color: #64748B;")
            self.alias_container.addWidget(lbl)
            return

        for st in self._devices[:5]:
            row = QHBoxLayout()
            row.setSpacing(8)
            kind_cn = {"mouse": "鼠标", "keyboard": "键盘"}.get(st.kind, "外设")
            lbl = QLabel(f"{kind_cn} ({st.connection_type})")
            lbl.setStyleSheet("font-size: 12px; color: #CBD5E1;")
            edit = QLineEdit()
            edit.setPlaceholderText(st.default_name)
            edit.setText(self._config.alias_for(st.device_key, st.kind, st.default_name))
            edit.setFixedWidth(195)
            row.addWidget(lbl, 1)
            row.addWidget(edit)
            self.alias_container.addLayout(row)
            self._alias_inputs[st.device_key] = edit

    def sync_settings_ui(self, cfg: AppConfig) -> None:
        """将当前配置同步回设置页控件。"""
        self._config = cfg
        self._select_combo_data(self.cmb_interval, cfg.poll_interval_sec)
        self._select_combo_data(self.cmb_tray_style, cfg.tray_style)
        self._select_combo_data(self.cmb_threshold, cfg.low_battery_threshold)
        self.chk_low_notify.setChecked(cfg.low_battery_notify)
        self.chk_autostart.setChecked(is_autostart_enabled())
        self.chk_floating.setChecked(cfg.show_floating_widget)
        self.chk_float_top.setChecked(cfg.floating_always_on_top)
        self._rebuild_alias_inputs()

    def set_polling_busy(self, busy: bool) -> None:
        """更新顶部刷新按钮忙碌状态。"""
        self.btn_refresh.setEnabled(not busy)
        self.btn_refresh.setText("检测中..." if busy else "刷新")

    def update_devices(self, devices: list[DeviceState], cfg: AppConfig) -> None:
        """根据当前已发现设备列表动态构建/更新卡片视图。"""
        self._config = cfg
        self._devices = list(devices)

        # 移除不再在列表中的旧卡片
        new_keys = {st.device_key for st in devices}
        for key in list(self._cards_by_key.keys()):
            if key not in new_keys:
                card = self._cards_by_key.pop(key)
                self.cards_layout.removeWidget(card)
                card.deleteLater()

        # 清除末尾 stretch 后重新按顺序插入卡片
        while self.cards_layout.count() > 0:
            last = self.cards_layout.itemAt(self.cards_layout.count() - 1)
            if last.spacerItem():
                self.cards_layout.takeAt(self.cards_layout.count() - 1)
            else:
                break

        self.empty_card.setVisible(len(devices) == 0)

        for idx, st in enumerate(devices):
            card = self._cards_by_key.get(st.device_key)
            if card is None:
                card = DeviceCard(st.kind, st.default_name, self.cards_host)
                self._cards_by_key[st.device_key] = card
            self.cards_layout.removeWidget(card)
            self.cards_layout.insertWidget(idx + 1, card)
            display_name = cfg.alias_for(st.device_key, st.kind, st.default_name)
            card.update_state(st, display_name)

        self.cards_layout.addStretch(1)

        # 根据设备数量自适应滚动区高度：1~2 台时无需滚动，3 台及以上限制最大高度
        if len(devices) == 0:
            self.scroll_area.setFixedHeight(120)
        elif len(devices) == 1:
            self.scroll_area.setFixedHeight(150)
        elif len(devices) == 2:
            self.scroll_area.setFixedHeight(304)
        else:
            self.scroll_area.setFixedHeight(390)

        online_cnt = sum(1 for d in devices if d.status != "disconnected")
        self.subtitle_label.setText(
            f"已接入 {online_cnt} 台外设 · 上次检测 {time.strftime('%H:%M:%S')}"
        )
        if self.stack.currentIndex() == 0:
            self.adjustSize()
            if self.isVisible():
                self.position_bottom_right()

    def _toggle_settings_page(self) -> None:
        if self.stack.currentIndex() == 0:
            self.sync_settings_ui(self._config)
            self.save_status_label.setText("")
            self.show_settings_page()
        else:
            self.show_overview_page()

    def show_overview_page(self) -> None:
        self.stack.setCurrentIndex(0)
        self.btn_settings.setText("设置")
        self.adjustSize()
        if self.isVisible():
            self.position_bottom_right()

    def show_settings_page(self) -> None:
        self.stack.setCurrentIndex(1)
        self.btn_settings.setText("返回")
        self.adjustSize()
        if self.isVisible():
            self.position_bottom_right()

    def _on_clear_disconnected(self) -> None:
        self.clear_disconnected_requested.emit()
        self.save_status_label.setText("已清理断开的历史设备")

    def _on_save_clicked(self) -> None:
        aliases = dict(self._config.device_aliases)
        for key, edit in self._alias_inputs.items():
            txt = edit.text().strip()
            if txt:
                aliases[key] = txt
            else:
                aliases.pop(key, None)

        new_cfg = AppConfig(
            poll_interval_sec=int(self.cmb_interval.currentData()),
            low_battery_notify=self.chk_low_notify.isChecked(),
            low_battery_threshold=int(self.cmb_threshold.currentData()),
            show_floating_widget=self.chk_floating.isChecked(),
            floating_always_on_top=self.chk_float_top.isChecked(),
            floating_opacity=self._config.floating_opacity,
            floating_pos=self._config.floating_pos,
            tray_style=str(self.cmb_tray_style.currentData()),
            mouse_alias=self._config.mouse_alias,
            keyboard_alias=self._config.keyboard_alias,
            device_aliases=aliases,
        )
        self.save_status_label.setText("设置已保存并生效")
        self.settings_saved.emit(new_cfg, self.chk_autostart.isChecked())

    def position_bottom_right(self) -> None:
        """定位在主屏幕可用区域右下角（紧贴任务栏上方留白 12px）。"""
        self.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.right() - self.width() - 12
        y = avail.bottom() - self.height() - 12
        self.move(max(avail.left() + 8, x), max(avail.top() + 8, y))

    def show_panel(self, page_index: int | None = None) -> None:
        """定位并显示飞出面板。"""
        if page_index == 1:
            self.sync_settings_ui(self._config)
            self.save_status_label.setText("")
            self.show_settings_page()
        elif page_index == 0:
            self.show_overview_page()

        self.position_bottom_right()
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_panel(self) -> None:
        """隐藏飞出面板并记录时间戳供托盘单击防抖。"""
        if self.isVisible():
            self.last_hidden_ts = time.monotonic()
            self.hide()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if not self._suppress_auto_hide and not self._any_popup_active():
                self.hide_panel()
        super().changeEvent(event)

    def _any_popup_active(self) -> bool:
        return any(
            cmb.view().isVisible()
            for cmb in (self.cmb_interval, self.cmb_tray_style, self.cmb_threshold)
        )
