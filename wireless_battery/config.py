# -*- coding: utf-8 -*-
"""应用配置持久化与 Windows 开机自启动管理。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys
import winreg

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "WirelessBatteryMonitor"


def get_app_root() -> Path:
    """获取程序根目录（兼容脚本运行与 PyInstaller 打包模式）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """获取持久化数据目录并确保其存在。"""
    data_dir = get_app_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@dataclass(slots=True)
class AppConfig:
    """应用程序用户配置。"""

    poll_interval_sec: int = 120
    low_battery_notify: bool = True
    low_battery_threshold: int = 20
    show_floating_widget: bool = False
    floating_always_on_top: bool = True
    floating_opacity: float = 0.92
    floating_pos: list[int] | None = None
    tray_style: str = "dual_number"  # "dual_number" 或 "dual_bar"
    mouse_alias: str = ""
    keyboard_alias: str = ""
    device_aliases: dict[str, str] = field(default_factory=dict)

    def alias_for(self, device_key: str, kind: str, fallback: str) -> str:
        """按 device_key 优先返回用户自定义名称，向下兼容旧的 mouse/keyboard_alias。"""
        custom = self.device_aliases.get(device_key, "").strip()
        if custom:
            return custom

        # 向下兼容旧版配置文件（针对原本用户的两台核心设备）
        if device_key == "mouse_3554_fb3e" and self.mouse_alias.strip():
            return self.mouse_alias.strip()
        if device_key == "keyboard_3554_fa09" and self.keyboard_alias.strip():
            return self.keyboard_alias.strip()

        return fallback


def get_config_path() -> Path:
    """获取配置文件路径。"""
    return get_data_dir() / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    """从磁盘加载配置；若不存在或损坏则返回默认配置。"""
    cfg_path = path or get_config_path()
    if not cfg_path.exists():
        return AppConfig()
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return AppConfig()
        defaults = AppConfig()
        raw_aliases = raw.get("device_aliases", {})
        aliases = (
            {str(k): str(v) for k, v in raw_aliases.items() if str(v).strip()}
            if isinstance(raw_aliases, dict)
            else {}
        )
        return AppConfig(
            poll_interval_sec=int(raw.get("poll_interval_sec", defaults.poll_interval_sec)),
            low_battery_notify=bool(raw.get("low_battery_notify", defaults.low_battery_notify)),
            low_battery_threshold=int(raw.get("low_battery_threshold", defaults.low_battery_threshold)),
            show_floating_widget=bool(raw.get("show_floating_widget", defaults.show_floating_widget)),
            floating_always_on_top=bool(
                raw.get("floating_always_on_top", defaults.floating_always_on_top)
            ),
            floating_opacity=float(raw.get("floating_opacity", defaults.floating_opacity)),
            floating_pos=raw.get("floating_pos", defaults.floating_pos),
            tray_style=str(raw.get("tray_style", defaults.tray_style)),
            mouse_alias=str(raw.get("mouse_alias", "")),
            keyboard_alias=str(raw.get("keyboard_alias", "")),
            device_aliases=aliases,
        )
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """将配置写入 JSON 文件。"""
    cfg_path = path or get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_autostart_command() -> str:
    """构造写入注册表 Run 项的静默启动命令。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'

    exe = Path(sys.executable).resolve()
    pythonw = exe.with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else exe
    run_pyw = get_app_root() / "run.pyw"
    entry = run_pyw if run_pyw.exists() else (get_app_root() / "run.py")
    return f'"{launcher}" "{entry}"'


def is_autostart_enabled() -> bool:
    """检查当前是否已启用开机自启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_REG_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool) -> tuple[bool, str]:
    """开启或关闭当前用户开机自启。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                cmd = build_autostart_command()
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
                return True, "已开启开机自启动"
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass
            return True, "已关闭开机自启动"
    except OSError as exc:
        return False, f"修改开机自启注册表失败: {exc}"
