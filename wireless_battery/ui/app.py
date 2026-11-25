# -*- coding: utf-8 -*-
"""Windows 系统托盘主控制器、单实例保护与多设备轮询调度。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from ..config import (
    AppConfig,
    is_autostart_enabled,
    load_config,
    save_config,
    set_autostart,
)
from ..models import BatteryStore, DeviceState, LowBatteryTracker
from ..worker import PollCoordinator
from .flyout import BatteryFlyout
from .icons import create_app_icon, create_tray_icon
from .widgets import FloatingBatteryWidget

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\WirelessBatteryMonitorMutex"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstanceGuard:
    """基于 Win32 命名互斥锁的单实例防重复运行保护。"""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._handle = _kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def pick_primary_devices(devices: list[DeviceState]) -> list[DeviceState]:
    """从全部设备中选出最适合展示在托盘与悬浮窗的前两台代表设备（优先主鼠标+主键盘）。"""
    active = [d for d in devices if d.status != "disconnected"] or list(devices)
    if not active:
        return []

    mouse = next((d for d in active if d.kind == "mouse"), None)
    keyboard = next((d for d in active if d.kind == "keyboard"), None)
    chosen: list[DeviceState] = []
    if mouse is not None:
        chosen.append(mouse)
    if keyboard is not None and keyboard is not mouse:
        chosen.append(keyboard)

    for d in active:
        if len(chosen) >= 2:
            break
        if d not in chosen:
            chosen.append(d)
    return chosen


class WirelessBatteryApp:
    """无线外设电量监控软件主控制器。"""

    def __init__(self, app: QApplication, smoke_test: bool = False) -> None:
        self.app = app
        self.smoke_test = smoke_test
        self.config: AppConfig = load_config()
        self.store = BatteryStore()
        self.low_tracker = LowBatteryTracker(hysteresis=5)
        self.coordinator = PollCoordinator()

        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("无线外设电量监控")
        self.app.setWindowIcon(create_app_icon())

        # 初始化主飞出面板（默认隐藏，点击托盘图标弹出）
        self.flyout = BatteryFlyout(self.config)
        self.flyout.refresh_requested.connect(self.trigger_manual_poll)
        self.flyout.settings_saved.connect(self._on_settings_saved)
        self.flyout.clear_disconnected_requested.connect(self._on_clear_disconnected)
        self.flyout.exit_requested.connect(self.quit_app)

        # 初始化可选桌面悬浮窗（默认关闭）
        self.floating = FloatingBatteryWidget()
        self.floating.open_flyout_requested.connect(lambda: self._open_flyout(page_index=0))
        self.floating.refresh_requested.connect(self.trigger_manual_poll)
        self.floating.hide_requested.connect(self._hide_floating)
        self.floating.toggle_top_requested.connect(self._toggle_floating_top)
        self.floating.position_changed.connect(self._save_floating_pos)
        self._apply_floating_config()

        # 初始化右下角系统托盘图标与右键菜单
        self.tray = QSystemTrayIcon(self.app)
        self._build_tray_menu()
        self.tray.activated.connect(self._on_tray_activated)

        # 绑定后台轮询信号
        self.coordinator.poll_started.connect(lambda: self.flyout.set_polling_busy(True))
        self.coordinator.poll_finished.connect(self._on_poll_finished)

        # 定时轮询器
        self.poll_timer = QTimer(self.app)
        self.poll_timer.timeout.connect(self.coordinator.trigger_poll)
        self._restart_timer()

        self._refresh_all_views(check_notify=False)
        self.tray.show()

        QTimer.singleShot(150, self.coordinator.trigger_poll)

    def _build_tray_menu(self) -> None:
        menu = QMenu()
        self.act_toggle_panel = QAction("显示 / 隐藏电量面板", menu)
        self.act_toggle_panel.triggered.connect(self._toggle_flyout_from_menu)

        self.act_refresh = QAction("立即刷新电量", menu)
        self.act_refresh.triggered.connect(self.trigger_manual_poll)

        self.act_floating = QAction("显示桌面悬浮窗", menu)
        self.act_floating.setCheckable(True)
        self.act_floating.setChecked(self.config.show_floating_widget)
        self.act_floating.triggered.connect(self._on_tray_toggle_floating)

        self.act_autostart = QAction("开机自动启动", menu)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(is_autostart_enabled())
        self.act_autostart.triggered.connect(self._on_tray_toggle_autostart)

        self.act_settings = QAction("设置...", menu)
        self.act_settings.triggered.connect(lambda: self._open_flyout(page_index=1))

        self.act_quit = QAction("退出", menu)
        self.act_quit.triggered.connect(self.quit_app)

        menu.addAction(self.act_toggle_panel)
        menu.addAction(self.act_refresh)
        menu.addSeparator()
        menu.addAction(self.act_floating)
        menu.addAction(self.act_autostart)
        menu.addAction(self.act_settings)
        menu.addSeparator()
        menu.addAction(self.act_quit)

        self.tray.setContextMenu(menu)

    def _restart_timer(self) -> None:
        interval_ms = max(15, int(self.config.poll_interval_sec)) * 1000
        self.poll_timer.start(interval_ms)

    def _apply_floating_config(self) -> None:
        self.floating.apply_settings(
            always_on_top=self.config.floating_always_on_top,
            opacity=self.config.floating_opacity,
        )
        if self.config.floating_pos and len(self.config.floating_pos) == 2:
            self.floating.move(int(self.config.floating_pos[0]), int(self.config.floating_pos[1]))
        if self.config.show_floating_widget and not self.smoke_test:
            self.floating.show()
        else:
            self.floating.hide()

    def trigger_manual_poll(self) -> None:
        self.coordinator.trigger_poll()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.flyout.isVisible():
                self.flyout.hide_panel()
                return
            if (time.monotonic() - self.flyout.last_hidden_ts) < 0.25:
                return
            self._open_flyout(page_index=0)

    def _toggle_flyout_from_menu(self) -> None:
        if self.flyout.isVisible():
            self.flyout.hide_panel()
        else:
            self._open_flyout(page_index=0)

    def _open_flyout(self, page_index: int = 0) -> None:
        self.flyout.show_panel(page_index=page_index)
        if page_index == 0:
            self.coordinator.trigger_poll()

    def _on_tray_toggle_floating(self, checked: bool) -> None:
        self.config.show_floating_widget = checked
        save_config(self.config)
        self._apply_floating_config()

    def _hide_floating(self) -> None:
        self.config.show_floating_widget = False
        self.act_floating.setChecked(False)
        save_config(self.config)
        self.floating.hide()

    def _toggle_floating_top(self, on_top: bool) -> None:
        self.config.floating_always_on_top = on_top
        save_config(self.config)
        self._apply_floating_config()

    def _save_floating_pos(self, x: int, y: int) -> None:
        self.config.floating_pos = [x, y]
        save_config(self.config)

    def _on_tray_toggle_autostart(self, checked: bool) -> None:
        ok, msg = set_autostart(checked)
        self.act_autostart.setChecked(is_autostart_enabled())
        if not ok:
            self.tray.showMessage("开机自启设置失败", msg, QSystemTrayIcon.MessageIcon.Warning, 3500)

    def _on_clear_disconnected(self) -> None:
        self.store.clear_disconnected_devices()
        self._refresh_all_views(check_notify=False)
        self.flyout.sync_settings_ui(self.config)

    def _on_settings_saved(self, new_cfg: AppConfig, autostart_enabled: bool) -> None:
        self.config = new_cfg
        save_config(self.config)
        set_autostart(autostart_enabled)

        self.act_floating.setChecked(self.config.show_floating_widget)
        self.act_autostart.setChecked(is_autostart_enabled())
        self._apply_floating_config()
        self._restart_timer()
        self._refresh_all_views(check_notify=False)

    def _on_poll_finished(self, results: list) -> None:
        self.flyout.set_polling_busy(False)
        self.store.apply_poll_results(results)
        self._refresh_all_views(check_notify=not self.smoke_test)

        if self.smoke_test:
            self._print_smoke_summary()
            QTimer.singleShot(450, self.quit_app)

    def _format_tooltip_line(self, label: str, st: DeviceState) -> str:
        if st.battery is None:
            return f"{label}: 暂无数据 ({st.status_label})"
        extra = ""
        if st.charging is True:
            extra = " · 充电中"
        elif st.status == "sleeping":
            extra = " (休眠缓存)"
        elif st.voltage_mv:
            extra = f" ({st.voltage_mv / 1000:.2f}V)"
        return f"{label}: {st.battery}%{extra}"

    def _refresh_all_views(self, check_notify: bool) -> None:
        devices = self.store.get_ordered_devices()
        primary = pick_primary_devices(devices)

        self.tray.setIcon(create_tray_icon(primary, self.config.tray_style))

        tip_lines = ["无线外设电量监控"]
        if not devices:
            tip_lines.append("暂未检测到兼容外设")
        else:
            for st in devices[:5]:
                name = self.config.alias_for(st.device_key, st.kind, st.default_name)
                tip_lines.append(self._format_tooltip_line(name, st))
        self.tray.setToolTip("\n".join(tip_lines))

        self.flyout.update_devices(devices, self.config)
        self.floating.update_states(primary)

        if check_notify:
            for st in devices:
                name = self.config.alias_for(st.device_key, st.kind, st.default_name)
                if self.low_tracker.check(
                    st,
                    enabled=self.config.low_battery_notify,
                    threshold=self.config.low_battery_threshold,
                ):
                    self.tray.showMessage(
                        "外设低电量提醒",
                        f"{name} 当前电量仅剩 {st.battery}%，请及时充电。",
                        QSystemTrayIcon.MessageIcon.Warning,
                        5000,
                    )

    def _print_smoke_summary(self) -> None:
        devices = self.store.get_ordered_devices()
        print(f"[冒烟自检] Qt 托盘、多设备飞出面板与后台发现轮询成功，共识别 {len(devices)} 台设备")
        for st in devices:
            print(
                f"  - [{st.connection_type}/{st.protocol}] {st.default_name} "
                f"(key={st.device_key}, kind={st.kind}): 状态={st.status_label}, 电量={st.battery}%"
            )

    def quit_app(self) -> None:
        self.poll_timer.stop()
        self.coordinator.stop_and_wait(1500)
        self.flyout.hide()
        self.floating.hide()
        self.tray.hide()
        self.app.quit()


def main(argv: list[str] | None = None) -> int:
    """应用程序主入口。"""
    args = argv if argv is not None else sys.argv[1:]
    smoke_test = "--smoke-test" in args

    guard: SingleInstanceGuard | None = None
    if not smoke_test:
        guard = SingleInstanceGuard()

    app = QApplication(sys.argv)
    if guard and guard.already_running:
        QMessageBox.information(
            None,
            "无线外设电量监控",
            "程序已在运行中，请在屏幕右下角系统托盘查看图标。",
        )
        guard.release()
        return 0

    controller = WirelessBatteryApp(app, smoke_test=smoke_test)
    if smoke_test:
        controller.flyout.show_panel(page_index=0)

    try:
        return app.exec()
    finally:
        if guard:
            guard.release()
