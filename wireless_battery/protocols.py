# -*- coding: utf-8 -*-
"""多品牌无线外设协议发现、报文构造与响应解析。

支持以下四大协议体系：
1. 国产 Compx / CX 2.4G 全系通配（VID=0x3554 / 0x373B / 0x373E，VGN/VXE/ATK/迈从/狼蛛/Story65/LEOBOG/黑爵等）
2. 罗技（Logitech，VID=0x046D）HID++ 2.0（Lightspeed / Unifying / Logi Bolt）
3. 雷蛇（Razer，VID=0x1532）90 字节 HID Feature Report 协议
4. 全品牌 Windows 蓝牙无线外设（BLE GATT 电池属性）
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from .hid_win import (
    ERROR_ACCESS_DENIED,
    HidDeviceInfo,
    PnpBatteryDevice,
    close_handle,
    enumerate_hid_devices,
    enumerate_pnp_battery_devices,
    flush_queue,
    get_feature_report,
    open_hid_feature,
    open_hid_rw,
    read_report_overlapped,
    set_feature_report,
    write_report_overlapped,
)

COMPX_VIDS = frozenset({0x3554, 0x373B, 0x373E})
LOGITECH_VID = 0x046D
RAZER_VID = 0x1532

LOGI_SW_ID = 0x0A


@dataclass(slots=True)
class PollResult:
    """单次设备电量轮询结果。"""

    device_key: str
    default_name: str
    kind: str  # "mouse" | "keyboard" | "other"
    vid: int
    pid: int
    connected: bool
    online: bool
    battery: int | None = None
    charging: bool | None = None
    voltage_mv: int | None = None
    raw_hex: str = ""
    status_flag: int | None = None
    error: str = ""
    connection_type: str = "2.4G"
    protocol: str = ""


def format_hex(data: bytes) -> str:
    """将字节序列格式化为大写的空格分隔十六进制文本。"""
    return " ".join(f"{b:02X}" for b in data)


def voltage_mv_to_percent(voltage_mv: int) -> int:
    """根据标准单节锂电池放电曲线将毫伏电压近似换算为百分比（用于仅上报电压的设备）。"""
    if voltage_mv >= 4180:
        return 100
    if voltage_mv <= 3300:
        return 0
    # 分段线性近似（4.18V~3.70V 约占 100%~20%，3.70V~3.30V 约占 20%~0%）
    if voltage_mv >= 3700:
        return min(100, int(20 + (voltage_mv - 3700) * 80 / (4180 - 3700)))
    return max(0, int((voltage_mv - 3300) * 20 / (3700 - 3300)))


# ==============================================================================
# 1. 国产 Compx / CX 2.4G 全系通配协议
# ==============================================================================


def build_mouse_query_packet(base_checksum: int = 0x55) -> bytes:
    """构造 17 字节 Compx 鼠标电量查询帧（默认使用 0x55 校验基准）。"""
    frame = [0] * 17
    frame[0] = 0x08
    frame[1] = 0x04
    frame[16] = (base_checksum - sum(frame[:16])) & 0xFF
    return bytes(frame)


def build_keyboard_query_packet() -> bytes:
    """构造 20 字节 Compx 键盘电量查询帧（0x13 0x4A 0x01）。"""
    frame = [0] * 20
    frame[0] = 0x13
    frame[1] = 0x4A
    frame[2] = 0x01
    frame[19] = sum(frame[:19]) & 0xFF
    return bytes(frame)


def parse_mouse_response(
    resp: bytes,
    *,
    device_key: str = "mouse_3554_fb3e",
    default_name: str = "VGN DragonFly F2 Pro Max",
    vid: int = 0x3554,
    pid: int = 0xFB3E,
    kind: str = "mouse",
) -> PollResult | None:
    """解析 Compx 17 字节电量响应；若非目标响应帧或校验错误帧返回 None。"""
    if len(resp) < 10 or resp[0] != 0x08 or resp[1] != 0x04:
        return None
    if resp[2] != 0x00:
        return None

    raw_hex = format_hex(resp)
    conn_flag = resp[5]

    if conn_flag == 0x00:
        return PollResult(
            device_key=device_key,
            default_name=default_name,
            kind=kind,
            vid=vid,
            pid=pid,
            connected=True,
            online=False,
            raw_hex=raw_hex,
            status_flag=conn_flag,
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )

    online = conn_flag == 0x02
    battery_raw = resp[6]
    battery = battery_raw if 0 <= battery_raw <= 100 else None
    charging = resp[7] == 0x01
    voltage_mv = (resp[8] << 8) | resp[9]

    return PollResult(
        device_key=device_key,
        default_name=default_name,
        kind=kind,
        vid=vid,
        pid=pid,
        connected=True,
        online=online,
        battery=battery,
        charging=charging,
        voltage_mv=voltage_mv if voltage_mv > 0 else None,
        raw_hex=raw_hex,
        status_flag=conn_flag,
        connection_type="2.4G",
        protocol="Compx 2.4G",
    )


def parse_keyboard_response(
    resp: bytes,
    *,
    device_key: str = "keyboard_3554_fa09",
    default_name: str = "2.4G 无线键盘",
    vid: int = 0x3554,
    pid: int = 0xFA09,
    kind: str = "keyboard",
) -> PollResult | None:
    """解析 Compx 20 字节键盘电量响应；若非目标响应帧返回 None。"""
    if len(resp) < 7 or resp[0] != 0x13 or resp[1] != 0x4A:
        return None

    raw_hex = format_hex(resp)
    conn_flag = resp[4]

    if conn_flag == 0x00:
        return PollResult(
            device_key=device_key,
            default_name=default_name,
            kind=kind,
            vid=vid,
            pid=pid,
            connected=True,
            online=False,
            raw_hex=raw_hex,
            status_flag=resp[6],
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )

    online = conn_flag == 0x02
    battery_raw = resp[5]
    battery = battery_raw if 0 <= battery_raw <= 100 else None
    status_flag = resp[6]

    return PollResult(
        device_key=device_key,
        default_name=default_name,
        kind=kind,
        vid=vid,
        pid=pid,
        connected=True,
        online=online,
        battery=battery,
        charging=None,
        voltage_mv=None,
        raw_hex=raw_hex,
        status_flag=status_flag,
        connection_type="2.4G",
        protocol="Compx 2.4G",
    )


def _send_and_wait_match(
    handle: int,
    packet: bytes,
    in_len: int,
    matcher: Callable[[bytes], object | None],
    timeout_sec: float = 0.85,
):
    """发送 HID 查询帧并在超时窗口内循环读取直到命中目标响应。"""
    flush_queue(handle)
    write_report_overlapped(handle, packet, timeout_ms=700)

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        rem_ms = max(60, int((deadline - time.monotonic()) * 1000))
        resp = read_report_overlapped(handle, in_len, timeout_ms=rem_ms)
        if resp is None:
            break
        parsed = matcher(resp)
        if parsed is not None:
            return parsed
    return None


def _friendly_compx_name(raw_product: str, kind: str, vid: int, pid: int) -> str:
    """清洗 Compx 公版产品字符串，避免出现无意义的通用接收器名。"""
    cleaned = raw_product.strip()
    generic_names = {"2.4g wireless receiver", "wireless receiver", "usb receiver", "compx 2.4g"}
    if not cleaned or cleaned.lower() in generic_names:
        return "2.4G 无线键盘" if kind == "keyboard" else "2.4G 无线鼠标"
    return cleaned


def _infer_compx_17b_kind(all_same_dev: list[HidDeviceInfo]) -> str:
    """当某 Compx 设备使用 17B 接口时，结合其标准集合判断是鼠标还是键盘。"""
    has_mouse = any(d.usage_page == 0x0001 and d.usage == 0x0002 for d in all_same_dev)
    has_kbd = any(d.usage_page == 0x0001 and d.usage == 0x0006 for d in all_same_dev)
    if has_kbd and not has_mouse:
        return "keyboard"
    return "mouse"


def _poll_compx_17b(info: HidDeviceInfo, kind: str, name: str, key: str) -> PollResult:
    try:
        handle = open_hid_rw(info.path)
    except OSError as exc:
        msg = "接口被占用或无权限，请关闭官方驱动后重试" if exc.errno == ERROR_ACCESS_DENIED else str(exc)
        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error=msg,
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )

    try:
        parser = lambda data: parse_mouse_response(
            data, device_key=key, default_name=name, vid=info.vid, pid=info.pid, kind=kind
        )
        for checksum_base in (0x55, 0x4D):
            pkt = build_mouse_query_packet(checksum_base)
            parsed = _send_and_wait_match(handle, pkt, info.in_len, parser, timeout_sec=0.85)
            if parsed is not None:
                return parsed

        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error="读取超时，设备可能处于深度休眠",
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )
    except OSError as exc:
        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error=f"HID 通信异常: {exc}",
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )
    finally:
        close_handle(handle)


def _poll_compx_20b(info: HidDeviceInfo, kind: str, name: str, key: str) -> PollResult:
    try:
        handle = open_hid_rw(info.path)
    except OSError as exc:
        msg = "接口被占用或无权限，请关闭官方驱动后重试" if exc.errno == ERROR_ACCESS_DENIED else str(exc)
        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error=msg,
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )

    try:
        parser = lambda data: parse_keyboard_response(
            data, device_key=key, default_name=name, vid=info.vid, pid=info.pid, kind=kind
        )
        pkt = build_keyboard_query_packet()
        parsed = _send_and_wait_match(handle, pkt, info.in_len, parser, timeout_sec=0.85)
        if parsed is not None:
            return parsed

        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error="读取超时，键盘可能处于休眠状态",
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )
    except OSError as exc:
        return PollResult(
            device_key=key,
            default_name=name,
            kind=kind,
            vid=info.vid,
            pid=info.pid,
            connected=True,
            online=False,
            error=f"HID 通信异常: {exc}",
            connection_type="2.4G",
            protocol="Compx 2.4G",
        )
    finally:
        close_handle(handle)


def _discover_and_poll_compx(hid_devices: list[HidDeviceInfo]) -> list[PollResult]:
    """通配发现并轮询所有 Compx 方案（0x3554 / 0x373B / 0x373E）无线外设。"""
    grouped: dict[tuple[int, int], list[HidDeviceInfo]] = {}
    for d in hid_devices:
        if d.vid in COMPX_VIDS:
            grouped.setdefault((d.vid, d.pid), []).append(d)

    results: list[PollResult] = []
    seen_keys: set[str] = set()

    for (vid, pid), interfaces in grouped.items():
        product_str = next((x.product for x in interfaces if x.product), "")
        for iface in interfaces:
            if iface.usage_page != 0xFF02 or iface.usage != 0x0002:
                continue

            if iface.in_len == 17 and iface.out_len == 17:
                kind = _infer_compx_17b_kind(interfaces)
                key = f"{kind}_{vid:04x}_{pid:04x}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                name = _friendly_compx_name(product_str, kind, vid, pid)
                results.append(_poll_compx_17b(iface, kind, name, key))
            elif iface.in_len == 20 and iface.out_len == 20:
                kind = "keyboard"
                key = f"{kind}_{vid:04x}_{pid:04x}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                name = _friendly_compx_name(product_str, kind, vid, pid)
                results.append(_poll_compx_20b(iface, kind, name, key))

    return results


# ==============================================================================
# 2. 罗技 Logitech HID++ 2.0 协议
# ==============================================================================


def build_hidpp_long_packet(
    dev_idx: int,
    feat_idx: int,
    func_id: int,
    params: bytes = b"",
    sw_id: int = LOGI_SW_ID,
) -> bytes:
    """构造 20 字节罗技 HID++ 2.0 长报告（Report ID = 0x11）。"""
    frame = bytearray(20)
    frame[0] = 0x11
    frame[1] = dev_idx & 0xFF
    frame[2] = feat_idx & 0xFF
    frame[3] = ((func_id & 0x0F) << 4) | (sw_id & 0x0F)
    for i, val in enumerate(params[:16]):
        frame[4 + i] = val
    return bytes(frame)


def is_hidpp_error(resp: bytes) -> bool:
    """判断是否为 HID++ 1.0/2.0 错误应答帧。"""
    return len(resp) >= 4 and resp[2] in (0x8F, 0xFF)


def parse_hidpp_unified_battery(resp: bytes) -> tuple[int, bool] | None:
    """解析罗技 HID++ 2.0 Unified Battery (0x1004, func=1) 响应，返回 (电量%, 是否充电)。"""
    if len(resp) < 7 or is_hidpp_error(resp):
        return None
    pct = resp[4]
    if not (0 <= pct <= 100):
        return None
    status_code = resp[6]
    # 1=充电中, 2=接近充满, 3=已充满, 4=慢速充电
    charging = status_code in (1, 2, 3, 4)
    return pct, charging


def parse_hidpp_battery_status(resp: bytes) -> tuple[int, bool] | None:
    """解析罗技 HID++ 2.0 Battery Status (0x1000, func=0) 响应。"""
    if len(resp) < 7 or is_hidpp_error(resp):
        return None
    pct = resp[4]
    if not (0 <= pct <= 100):
        return None
    status_code = resp[6]
    charging = status_code in (1, 2, 3, 4)
    return pct, charging


def parse_hidpp_battery_voltage(resp: bytes) -> tuple[int, int, bool] | None:
    """解析罗技 HID++ 2.0 Battery Voltage (0x1001, func=0) 响应，返回 (电量%, 电压mV, 是否充电)。"""
    if len(resp) < 7 or is_hidpp_error(resp):
        return None
    mv = (resp[4] << 8) | resp[5]
    if mv < 2500 or mv > 5000:
        return None
    pct = voltage_mv_to_percent(mv)
    charging = (resp[6] & 0x80) != 0 or resp[6] in (1, 2, 3)
    return pct, mv, charging


def _hidpp_call(
    handle: int,
    in_len: int,
    dev_idx: int,
    feat_idx: int,
    func_id: int,
    params: bytes = b"",
    timeout_sec: float = 0.22,
) -> bytes | None:
    pkt = build_hidpp_long_packet(dev_idx, feat_idx, func_id, params=params, sw_id=LOGI_SW_ID)

    def matcher(resp: bytes) -> bytes | None:
        if len(resp) < 7 or resp[1] != (dev_idx & 0xFF):
            return None
        # 允许接收错误帧（以便快速终止无用探测）或正常回包（sw_id 匹配）
        if is_hidpp_error(resp):
            return resp
        if resp[2] == (feat_idx & 0xFF) and (resp[3] & 0x0F) == LOGI_SW_ID:
            return resp
        return None

    return _send_and_wait_match(handle, pkt, in_len, matcher, timeout_sec=timeout_sec)


def _hidpp_find_feature(handle: int, in_len: int, dev_idx: int, feature_id: int) -> int | None:
    params = bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF])
    resp = _hidpp_call(handle, in_len, dev_idx, 0x00, 0x00, params=params, timeout_sec=0.22)
    if resp is None or is_hidpp_error(resp) or len(resp) < 5:
        return None
    idx = resp[4]
    return idx if idx != 0 else None


def _hidpp_query_name_and_kind(
    handle: int, in_len: int, dev_idx: int, fallback_name: str
) -> tuple[str, str]:
    feat_idx = _hidpp_find_feature(handle, in_len, dev_idx, 0x0005)
    name = fallback_name
    kind = "other"
    if feat_idx is None:
        lower = name.lower()
        if any(k in lower for k in ("keyboard", "key", "键盘", "g915", "mx keys", "k380")):
            return name, "keyboard"
        if any(k in lower for k in ("mouse", "g pro", "superlight", "master", "anywhere", "鼠标")):
            return name, "mouse"
        return name, "mouse"

    # Function 1: GetDeviceName(0)
    resp_name = _hidpp_call(handle, in_len, dev_idx, feat_idx, 0x01, params=b"\x00", timeout_sec=0.20)
    if resp_name and not is_hidpp_error(resp_name) and len(resp_name) > 4:
        raw_name = resp_name[4:].split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
        if raw_name:
            name = raw_name

    # Function 2: GetDeviceType
    resp_type = _hidpp_call(handle, in_len, dev_idx, feat_idx, 0x02, timeout_sec=0.20)
    if resp_type and not is_hidpp_error(resp_type) and len(resp_type) > 4:
        dev_type = resp_type[4]
        if dev_type == 0:
            kind = "keyboard"
        elif dev_type in (3, 4, 5):
            kind = "mouse"

    if kind == "other":
        lower = name.lower()
        if any(k in lower for k in ("keyboard", "key", "g915", "mx keys", "k380", "k855", "键盘")):
            kind = "keyboard"
        elif any(k in lower for k in ("mouse", "g pro", "superlight", "master", "anywhere", "g304", "g502", "鼠标")):
            kind = "mouse"

    return name, kind


def _poll_logitech_slot(
    handle: int, info: HidDeviceInfo, dev_idx: int
) -> PollResult | None:
    # 1. 先检查 Root Feature (0x0000) 是否可达
    f_1004 = _hidpp_find_feature(handle, info.in_len, dev_idx, 0x1004)
    f_1000 = None if f_1004 else _hidpp_find_feature(handle, info.in_len, dev_idx, 0x1000)
    f_1001 = None if (f_1004 or f_1000) else _hidpp_find_feature(handle, info.in_len, dev_idx, 0x1001)

    if not any((f_1004, f_1000, f_1001)):
        return None

    name, kind = _hidpp_query_name_and_kind(
        handle, info.in_len, dev_idx, info.product or "罗技无线设备"
    )
    key = f"logi_{info.vid:04x}_{info.pid:04x}_{dev_idx:02x}"

    battery: int | None = None
    charging: bool | None = None
    voltage_mv: int | None = None
    raw_hex = ""

    if f_1004:
        resp = _hidpp_call(handle, info.in_len, dev_idx, f_1004, 0x01, timeout_sec=0.35)
        if resp:
            raw_hex = format_hex(resp)
            parsed = parse_hidpp_unified_battery(resp)
            if parsed:
                battery, charging = parsed
    elif f_1000:
        resp = _hidpp_call(handle, info.in_len, dev_idx, f_1000, 0x00, timeout_sec=0.35)
        if resp:
            raw_hex = format_hex(resp)
            parsed = parse_hidpp_battery_status(resp)
            if parsed:
                battery, charging = parsed
    elif f_1001:
        resp = _hidpp_call(handle, info.in_len, dev_idx, f_1001, 0x00, timeout_sec=0.35)
        if resp:
            raw_hex = format_hex(resp)
            parsed = parse_hidpp_battery_voltage(resp)
            if parsed:
                battery, voltage_mv, charging = parsed

    return PollResult(
        device_key=key,
        default_name=name,
        kind=kind,
        vid=info.vid,
        pid=info.pid,
        connected=True,
        online=battery is not None,
        battery=battery,
        charging=charging,
        voltage_mv=voltage_mv,
        raw_hex=raw_hex,
        connection_type="2.4G",
        protocol="罗技 HID++",
    )


def _discover_and_poll_logitech(hid_devices: list[HidDeviceInfo]) -> list[PollResult]:
    """发现并轮询罗技 (0x046D) HID++ 2.0 无线外设。"""
    # 同一接收器可能暴露多个 FF00 接口，挑选支持 20 字节长报告的集合
    candidates: dict[tuple[int, int], HidDeviceInfo] = {}
    for d in hid_devices:
        if d.vid == LOGITECH_VID and d.usage_page == 0xFF00 and d.in_len >= 20 and d.out_len >= 20:
            pair = (d.vid, d.pid)
            # 优先 Usage=0x0002（长报告主集合）
            if pair not in candidates or d.usage == 0x0002:
                candidates[pair] = d

    results: list[PollResult] = []
    for info in candidates.values():
        try:
            handle = open_hid_rw(info.path)
        except OSError:
            continue

        try:
            # 先尝试直连索引 0xFF，未命中则扫描多设备接收器槽位 1..6
            direct = _poll_logitech_slot(handle, info, 0xFF)
            if direct is not None:
                results.append(direct)
                continue

            for slot in range(1, 7):
                slot_res = _poll_logitech_slot(handle, info, slot)
                if slot_res is not None:
                    results.append(slot_res)
        finally:
            close_handle(handle)

    return results


# ==============================================================================
# 3. 雷蛇 Razer 90 字节 HID Feature Report 协议
# ==============================================================================


def build_razer_feature_packet(
    cmd_class: int,
    cmd_id: int,
    transaction_id: int = 0x1F,
    args: bytes = b"",
) -> bytes:
    """构造标准 90 字节雷蛇 HID Feature 报文（含 Byte[88] XOR 校验）。"""
    pkt = bytearray(90)
    pkt[0] = 0x00
    pkt[1] = transaction_id & 0xFF
    pkt[5] = len(args) & 0xFF
    pkt[6] = cmd_class & 0xFF
    pkt[7] = cmd_id & 0xFF
    for i, val in enumerate(args[:80]):
        pkt[8 + i] = val

    xor_sum = 0
    for b in pkt[2:88]:
        xor_sum ^= b
    pkt[88] = xor_sum
    return bytes(pkt)


def parse_razer_battery_response(resp_90: bytes) -> int | None:
    """解析雷蛇 90 字节电量响应（0x07/0x80），返回 0..100 电量百分比。"""
    if len(resp_90) < 12:
        return None
    # Byte[0] 状态为 0x02 表示成功应答
    if resp_90[0] != 0x02 or resp_90[6] != 0x07 or resp_90[7] != 0x80:
        return None
    raw_val = resp_90[9]
    return max(0, min(100, round(raw_val * 100 / 255)))


def parse_razer_charging_response(resp_90: bytes) -> bool | None:
    """解析雷蛇 90 字节充电状态响应（0x07/0x84）。"""
    if len(resp_90) < 12:
        return None
    if resp_90[0] != 0x02 or resp_90[6] != 0x07 or resp_90[7] != 0x84:
        return None
    return resp_90[9] == 0x01


def _razer_query_90(
    handle: int, feat_len: int, cmd_class: int, cmd_id: int, transaction_id: int, args: bytes = b""
) -> bytes | None:
    payload = build_razer_feature_packet(cmd_class, cmd_id, transaction_id=transaction_id, args=args)
    if feat_len == 91:
        send_buf = b"\x00" + payload
    else:
        send_buf = payload

    if not set_feature_report(handle, send_buf):
        return None
    time.sleep(0.03)
    raw = get_feature_report(handle, 0x00, feat_len)
    if raw is None:
        return None
    return raw[1:91] if len(raw) == 91 else raw[:90]


def _discover_and_poll_razer(hid_devices: list[HidDeviceInfo]) -> list[PollResult]:
    """发现并轮询雷蛇 (0x1532) 支持 90 字节 Feature Report 的无线外设。"""
    grouped: dict[tuple[int, int], list[HidDeviceInfo]] = {}
    for d in hid_devices:
        if d.vid == RAZER_VID:
            grouped.setdefault((d.vid, d.pid), []).append(d)

    results: list[PollResult] = []
    for (vid, pid), interfaces in grouped.items():
        feat_iface = next((x for x in interfaces if x.feat_len in (90, 91)), None)
        if feat_iface is None:
            continue

        product_name = next((x.product for x in interfaces if x.product), "雷蛇无线设备")
        lower_name = product_name.lower()
        has_kbd = any(x.usage_page == 0x0001 and x.usage == 0x0006 for x in interfaces)
        has_mouse = any(x.usage_page == 0x0001 and x.usage == 0x0002 for x in interfaces)
        if "keyboard" in lower_name or "blackwidow" in lower_name or "deathstalker" in lower_name or (has_kbd and not has_mouse):
            kind = "keyboard"
        else:
            kind = "mouse"

        key = f"razer_{vid:04x}_{pid:04x}"
        try:
            handle = open_hid_feature(feat_iface.path)
        except OSError as exc:
            results.append(
                PollResult(
                    device_key=key,
                    default_name=product_name,
                    kind=kind,
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=False,
                    error=str(exc),
                    connection_type="2.4G",
                    protocol="雷蛇 2.4G",
                )
            )
            continue

        try:
            battery: int | None = None
            charging: bool | None = None
            raw_hex = ""
            for tx_id in (0x1F, 0x3F, 0xFF):
                resp_bat = _razer_query_90(handle, feat_iface.feat_len, 0x07, 0x80, tx_id, args=b"\x00\x00")
                if resp_bat:
                    parsed_bat = parse_razer_battery_response(resp_bat)
                    if parsed_bat is not None:
                        battery = parsed_bat
                        raw_hex = format_hex(resp_bat[:16])
                        resp_chg = _razer_query_90(
                            handle, feat_iface.feat_len, 0x07, 0x84, tx_id, args=b"\x00\x00"
                        )
                        if resp_chg:
                            charging = parse_razer_charging_response(resp_chg)
                        break

            results.append(
                PollResult(
                    device_key=key,
                    default_name=product_name,
                    kind=kind,
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=battery is not None,
                    battery=battery,
                    charging=charging,
                    raw_hex=raw_hex,
                    error="" if battery is not None else "设备未响应或已休眠",
                    connection_type="2.4G",
                    protocol="雷蛇 2.4G",
                )
            )
        finally:
            close_handle(handle)

    return results


# ==============================================================================
# 4. 全品牌 Windows 蓝牙无线外设（BLE GATT Battery Service）
# ==============================================================================


def infer_bluetooth_kind(name: str, dev_class: str = "") -> str:
    """根据蓝牙设备名称与 Windows 设备类别推断其属于鼠标、键盘还是其他外设。"""
    if dev_class == "Mouse":
        return "mouse"
    if dev_class == "Keyboard":
        return "keyboard"

    lower = name.lower()
    if any(k in lower for k in ("mouse", "trackball", "trackpad", "master", "anywhere", "鼠标")):
        return "mouse"
    if any(k in lower for k in ("keyboard", "keychron", "nuphy", "hhkb", "anne", "键盘")):
        return "keyboard"
    return "other"


def deduplicate_bluetooth_devices(devices: list[PnpBatteryDevice]) -> list[PnpBatteryDevice]:
    """对同 MAC 地址的多个蓝牙 PnP 节点去重，优先保留名称清晰度高的节点。"""
    best_by_mac: dict[str, PnpBatteryDevice] = {}
    for dev in devices:
        existing = best_by_mac.get(dev.mac_key)
        if existing is None:
            best_by_mac[dev.mac_key] = dev
            continue
        # 若新节点名称比旧节点更具体（非 GATT 通用名），则替换
        existing_generic = "GATT" in existing.name.upper() or existing.name == "蓝牙无线设备"
        new_generic = "GATT" in dev.name.upper() or dev.name == "蓝牙无线设备"
        if existing_generic and not new_generic:
            best_by_mac[dev.mac_key] = dev
    return list(best_by_mac.values())


def _discover_and_poll_bluetooth() -> list[PollResult]:
    """枚举当前系统中所有已连接并上报电量的蓝牙外设。"""
    raw_devices = enumerate_pnp_battery_devices()
    unique_devices = deduplicate_bluetooth_devices(raw_devices)
    results: list[PollResult] = []
    for dev in unique_devices:
        kind = infer_bluetooth_kind(dev.name, dev.dev_class)
        results.append(
            PollResult(
                device_key=f"bt_{dev.mac_key}",
                default_name=dev.name,
                kind=kind,
                vid=0,
                pid=0,
                connected=True,
                online=True,
                battery=dev.battery,
                charging=None,
                connection_type="蓝牙",
                protocol="蓝牙 GATT",
            )
        )
    return results


# ==============================================================================
# 统一轮询入口
# ==============================================================================


def poll_all_devices() -> list[PollResult]:
    """自动发现并轮询全部兼容无线外设（Compx 2.4G / 罗技 / 雷蛇 / 全品牌蓝牙）。"""
    results: list[PollResult] = []

    try:
        hid_devices = enumerate_hid_devices(target_vid=None)
    except Exception:
        hid_devices = []

    for discover_fn in (
        lambda: _discover_and_poll_compx(hid_devices),
        lambda: _discover_and_poll_logitech(hid_devices),
        lambda: _discover_and_poll_razer(hid_devices),
        _discover_and_poll_bluetooth,
    ):
        try:
            results.extend(discover_fn())
        except Exception:
            continue

    return results
