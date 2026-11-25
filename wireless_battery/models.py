# -*- coding: utf-8 -*-
"""多设备聚合状态模型、休眠缓存管理、历史记录与低电量防抖提醒机。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import time

from .config import get_data_dir
from .protocols import PollResult

MAX_HISTORY_POINTS = 120
MIN_HISTORY_INTERVAL_SEC = 60.0

_KIND_ORDER = {"mouse": 0, "keyboard": 1, "other": 2}
_STATUS_ORDER = {"online": 0, "sleeping": 1, "unknown": 2, "disconnected": 3}


@dataclass(slots=True)
class DeviceState:
    """单个无线外设的聚合视图状态（含休眠缓存与近期趋势）。"""

    device_key: str
    default_name: str
    kind: str  # "mouse" | "keyboard" | "other"
    vid: int
    pid: int
    status: str = "unknown"  # "online" | "sleeping" | "disconnected" | "unknown"
    battery: int | None = None
    is_cached: bool = False
    charging: bool | None = None
    voltage_mv: int | None = None
    status_flag: int | None = None
    last_updated_ts: float | None = None
    last_polled_ts: float | None = None
    last_error: str = ""
    raw_hex: str = ""
    connection_type: str = "2.4G"
    protocol: str = ""
    history: list[list[float]] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        """返回面向用户的中文状态徽章文案。"""
        if self.status == "online":
            if self.charging is True:
                return "充电中"
            return "在线"
        if self.status == "sleeping":
            return "休眠 · 上次记录" if self.battery is not None else "休眠中"
        if self.status == "disconnected":
            return "未连接"
        return "检测中"

    def formatted_update_time(self) -> str:
        """格式化上次有效电量读取时间。"""
        if not self.last_updated_ts:
            return "暂无记录"
        return time.strftime("%H:%M:%S", time.localtime(self.last_updated_ts))

    def to_dict(self) -> dict:
        """序列化为可落盘字典。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceState":
        """从字典反序列化设备状态（向下兼容旧版 state.json）。"""
        return cls(
            device_key=str(data.get("device_key", "")),
            default_name=str(data.get("default_name", "")),
            kind=str(data.get("kind", "mouse")),
            vid=int(data.get("vid", 0)),
            pid=int(data.get("pid", 0)),
            status=str(data.get("status", "unknown")),
            battery=data.get("battery"),
            is_cached=bool(data.get("is_cached", False)),
            charging=data.get("charging"),
            voltage_mv=data.get("voltage_mv"),
            status_flag=data.get("status_flag"),
            last_updated_ts=data.get("last_updated_ts"),
            last_polled_ts=data.get("last_polled_ts"),
            last_error=str(data.get("last_error", "")),
            raw_hex=str(data.get("raw_hex", "")),
            connection_type=str(data.get("connection_type", "2.4G")),
            protocol=str(data.get("protocol", "")),
            history=list(data.get("history", []))[-MAX_HISTORY_POINTS:],
        )


class BatteryStore:
    """多设备状态聚合与持久化管理器。"""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or (get_data_dir() / "state.json")
        self.states: dict[str, DeviceState] = {}
        self.load()

    def load(self) -> None:
        """从磁盘加载上次保存的设备状态和历史电量曲线。"""
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for key, item in raw.items():
                if isinstance(item, dict):
                    st = DeviceState.from_dict(item)
                    if st.battery is not None and st.status == "online":
                        st.status = "sleeping"
                        st.is_cached = True
                    self.states[key] = st
        except Exception:
            self.states = {}

    def save(self) -> None:
        """持久化当前设备状态到本地文件。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v.to_dict() for k, v in self.states.items()}
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def apply_poll_results(
        self, results: list[PollResult], now_ts: float | None = None
    ) -> list[DeviceState]:
        """将本轮动态发现的外设轮询结果合并到状态库，支持休眠缓存保护与拔出标离线。"""
        ts = time.time() if now_ts is None else now_ts
        seen_keys: set[str] = set()

        for res in results:
            seen_keys.add(res.device_key)
            state = self.states.get(res.device_key)
            if state is None:
                state = DeviceState(
                    device_key=res.device_key,
                    default_name=res.default_name,
                    kind=res.kind,
                    vid=res.vid,
                    pid=res.pid,
                )
                self.states[res.device_key] = state
            else:
                state.default_name = res.default_name
                state.kind = res.kind

            state.last_polled_ts = ts
            state.raw_hex = res.raw_hex
            state.last_error = res.error
            if res.connection_type:
                state.connection_type = res.connection_type
            if res.protocol:
                state.protocol = res.protocol

            if not res.connected:
                state.status = "disconnected"
                state.is_cached = state.battery is not None
                state.charging = None
            elif res.online and res.battery is not None:
                state.status = "online"
                state.battery = res.battery
                state.is_cached = False
                state.charging = res.charging
                if res.voltage_mv is not None:
                    state.voltage_mv = res.voltage_mv
                state.status_flag = res.status_flag
                state.last_updated_ts = ts
                self._append_history(state, ts, res.battery)
            else:
                state.status = "sleeping"
                state.is_cached = state.battery is not None
                if res.status_flag is not None:
                    state.status_flag = res.status_flag

        # 本轮未发现的旧设备自动标记为未连接（保留历史电量记录）
        for key, st in self.states.items():
            if key not in seen_keys:
                st.status = "disconnected"
                st.is_cached = st.battery is not None
                st.charging = None
                st.last_polled_ts = ts
                st.last_error = "未检测到设备或接收器已拔出"

        self.save()
        return self.get_ordered_devices()

    def clear_disconnected_devices(self) -> int:
        """移除所有当前处于未连接状态的历史设备，返回清理数量。"""
        to_remove = [k for k, v in self.states.items() if v.status == "disconnected"]
        for k in to_remove:
            del self.states[k]
        if to_remove:
            self.save()
        return len(to_remove)

    @staticmethod
    def _append_history(state: DeviceState, ts: float, battery: int) -> None:
        """记录历史采样点，避免短时间内重复写入冗余点。"""
        if state.history:
            last_ts, last_bat = state.history[-1]
            if (ts - last_ts) < MIN_HISTORY_INTERVAL_SEC and int(last_bat) == battery:
                return
        state.history.append([round(ts, 1), int(battery)])
        if len(state.history) > MAX_HISTORY_POINTS:
            state.history = state.history[-MAX_HISTORY_POINTS:]

    def get_ordered_devices(self) -> list[DeviceState]:
        """按 在线状态优先 + 鼠标/键盘/其他顺序 返回全部设备列表。"""
        return sorted(
            self.states.values(),
            key=lambda s: (
                0 if s.status != "disconnected" else 1,
                _KIND_ORDER.get(s.kind, 9),
                _STATUS_ORDER.get(s.status, 9),
                s.device_key,
            ),
        )

    def get_by_kind(self, kind: str) -> DeviceState | None:
        """按设备类别获取排在最前的设备状态。"""
        for st in self.get_ordered_devices():
            if st.kind == kind:
                return st
        return None


class LowBatteryTracker:
    """低电量防抖提醒控制器，避免连续轮询时重复弹窗。"""

    def __init__(self, hysteresis: int = 5) -> None:
        self.hysteresis = hysteresis
        self._notified_keys: set[str] = set()

    def check(self, state: DeviceState, enabled: bool, threshold: int) -> bool:
        """判断本次是否应该弹出低电量提醒。"""
        if not enabled or state.battery is None:
            return False

        if state.charging is True or state.battery >= threshold + self.hysteresis:
            self._notified_keys.discard(state.device_key)
            return False

        if state.status != "online" or state.is_cached:
            return False

        if state.battery <= threshold and state.device_key not in self._notified_keys:
            self._notified_keys.add(state.device_key)
            return True

        return False
