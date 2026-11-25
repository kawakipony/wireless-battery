# -*- coding: utf-8 -*-
"""Windows 原生 HID 与蓝牙 PnP 电量属性枚举封装（基于 ctypes，零外部依赖）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import re

# ==============================================================================
# Win32 常量与结构体
# ==============================================================================

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000

DIGCF_PRESENT = 0x00000002
DIGCF_ALLCLASSES = 0x00000004
DIGCF_DEVICEINTERFACE = 0x00000010

WAIT_OBJECT_0 = 0x00000000
ERROR_IO_PENDING = 997
ERROR_ACCESS_DENIED = 5
ERROR_INSUFFICIENT_BUFFER = 122

SPDRP_DEVICEDESC = 0x00000000
SPDRP_CLASS = 0x00000007
SPDRP_FRIENDLYNAME = 0x0000000C

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    """Windows GUID 结构体。"""

    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class DEVPROPKEY(ctypes.Structure):
    """Windows 设备属性键结构体。"""

    _fields_ = [
        ("fmtid", GUID),
        ("pid", wintypes.ULONG),
    ]


class SP_DEVINFO_DATA(ctypes.Structure):
    """PnP 设备信息枚举结构体。"""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    """设备接口枚举数据结构。"""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    """HID 设备 VID/PID/版本属性。"""

    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    """HID 设备集合能力描述。"""

    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


class OVERLAPPED(ctypes.Structure):
    """Windows 异步 I/O 控制结构。"""

    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


@dataclass(slots=True)
class HidDeviceInfo:
    """已枚举的 HID 接口信息。"""

    vid: int
    pid: int
    product: str
    usage_page: int
    usage: int
    in_len: int
    out_len: int
    feat_len: int
    path: str


@dataclass(slots=True)
class PnpBatteryDevice:
    """通过 Windows PnP 属性获取电量的蓝牙外设信息。"""

    instance_id: str
    mac_key: str
    name: str
    dev_class: str
    battery: int


# ==============================================================================
# 加载系统 DLL 并显式声明参数/返回值类型（64 位安全）
# ==============================================================================

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid_dll = ctypes.WinDLL("hid", use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.CreateEventW.argtypes = [
    ctypes.c_void_p,
    wintypes.BOOL,
    wintypes.BOOL,
    wintypes.LPCWSTR,
]
kernel32.CreateEventW.restype = wintypes.HANDLE

kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

kernel32.GetOverlappedResult.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(OVERLAPPED),
    ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL,
]
kernel32.GetOverlappedResult.restype = wintypes.BOOL

kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CancelIoEx.restype = wintypes.BOOL

kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(OVERLAPPED),
]
kernel32.ReadFile.restype = wintypes.BOOL

kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(OVERLAPPED),
]
kernel32.WriteFile.restype = wintypes.BOOL

setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID),
    wintypes.LPCWSTR,
    wintypes.HWND,
    wintypes.DWORD,
]
setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p

setupapi.SetupDiEnumDeviceInfo.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVINFO_DATA),
]
setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    wintypes.LPWSTR,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL

setupapi.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVINFO_DATA),
    ctypes.POINTER(DEVPROPKEY),
    ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL

setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(GUID),
    wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL

setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

hid_dll.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid_dll.HidD_GetHidGuid.restype = None

hid_dll.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid_dll.HidD_GetAttributes.restype = wintypes.BOOL

hid_dll.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_GetProductString.restype = wintypes.BOOL

hid_dll.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid_dll.HidD_GetPreparsedData.restype = wintypes.BOOL

hid_dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid_dll.HidD_FreePreparsedData.restype = wintypes.BOOL

hid_dll.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid_dll.HidP_GetCaps.restype = ctypes.c_long

hid_dll.HidD_FlushQueue.argtypes = [wintypes.HANDLE]
hid_dll.HidD_FlushQueue.restype = wintypes.BOOL

hid_dll.HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_SetOutputReport.restype = wintypes.BOOL

hid_dll.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_SetFeature.restype = wintypes.BOOL

hid_dll.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid_dll.HidD_GetFeature.restype = wintypes.BOOL


# Windows 蓝牙电池属性键 {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, PID=2
DEVPKEY_DEVICE_BATTERY = DEVPROPKEY(
    fmtid=GUID(
        Data1=0x104EA319,
        Data2=0x6EE2,
        Data3=0x4701,
        Data4=(ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5),
    ),
    pid=2,
)

_BT_PREFIXES = ("BTH\\", "BTHENUM\\", "BTHLE\\", "BTHLEDEVICE\\")
_MAC_RE = re.compile(r"([0-9A-Fa-f]{12})")


# ==============================================================================
# HID 接口枚举与读写封装
# ==============================================================================


def enumerate_hid_devices(target_vid: int | None = None) -> list[HidDeviceInfo]:
    """枚举当前系统中符合目标 VID（None 表示全部）的所有 HID 接口。"""
    hid_guid = GUID()
    hid_dll.HidD_GetHidGuid(ctypes.byref(hid_guid))

    dev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(hid_guid),
        None,
        None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if not dev_info or dev_info == INVALID_HANDLE_VALUE:
        raise OSError(f"SetupDiGetClassDevsW 失败，错误码: {ctypes.get_last_error()}")

    results: list[HidDeviceInfo] = []
    cb_detail_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6

    try:
        idx = 0
        if_data = SP_DEVICE_INTERFACE_DATA()
        if_data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)

        while setupapi.SetupDiEnumDeviceInterfaces(
            dev_info, None, ctypes.byref(hid_guid), idx, ctypes.byref(if_data)
        ):
            idx += 1
            req_size = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info, ctypes.byref(if_data), None, 0, ctypes.byref(req_size), None
            )
            if req_size.value == 0:
                continue

            detail_buf = ctypes.create_string_buffer(req_size.value)
            ctypes.cast(detail_buf, ctypes.POINTER(wintypes.DWORD))[0] = cb_detail_size

            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info,
                ctypes.byref(if_data),
                detail_buf,
                req_size.value,
                ctypes.byref(req_size),
                None,
            ):
                continue

            device_path = ctypes.wstring_at(ctypes.addressof(detail_buf) + 4)

            handle = kernel32.CreateFileW(
                device_path,
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                continue

            try:
                attr = HIDD_ATTRIBUTES()
                attr.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
                if not hid_dll.HidD_GetAttributes(handle, ctypes.byref(attr)):
                    continue
                if target_vid is not None and attr.VendorID != target_vid:
                    continue

                prod_buf = ctypes.create_unicode_buffer(128)
                product_name = ""
                if hid_dll.HidD_GetProductString(handle, prod_buf, ctypes.sizeof(prod_buf)):
                    product_name = prod_buf.value.strip()

                pp_data = ctypes.c_void_p()
                caps = HIDP_CAPS()
                if hid_dll.HidD_GetPreparsedData(handle, ctypes.byref(pp_data)):
                    try:
                        hid_dll.HidP_GetCaps(pp_data, ctypes.byref(caps))
                    finally:
                        hid_dll.HidD_FreePreparsedData(pp_data)

                results.append(
                    HidDeviceInfo(
                        vid=attr.VendorID,
                        pid=attr.ProductID,
                        product=product_name,
                        usage_page=caps.UsagePage,
                        usage=caps.Usage,
                        in_len=caps.InputReportByteLength,
                        out_len=caps.OutputReportByteLength,
                        feat_len=caps.FeatureReportByteLength,
                        path=device_path,
                    )
                )
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)

    return results


def open_hid_rw(device_path: str, access: int = GENERIC_READ | GENERIC_WRITE) -> int:
    """以异步读写共享模式打开 HID 接口句柄。"""
    handle = kernel32.CreateFileW(
        device_path,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise OSError(err, f"无法打开 HID 设备句柄 (错误码 {err})")
    return handle


def open_hid_feature(device_path: str) -> int:
    """打开用于 Feature Report 通信的 HID 句柄（优先读写权限，失败回退属性只读句柄）。"""
    try:
        return open_hid_rw(device_path, GENERIC_READ | GENERIC_WRITE)
    except OSError:
        handle = kernel32.CreateFileW(
            device_path,
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise OSError(err, f"无法打开 Feature 接口 (错误码 {err})")
        return handle


def close_handle(handle: int | None) -> None:
    """安全关闭 Win32 句柄。"""
    if handle and handle != INVALID_HANDLE_VALUE:
        kernel32.CloseHandle(handle)


def flush_queue(handle: int) -> None:
    """清空 HID 驱动输入队列中的历史残留报告。"""
    hid_dll.HidD_FlushQueue(handle)


def write_report_overlapped(handle: int, packet: bytes, timeout_ms: int = 800) -> None:
    """向 HID 接口发送 Output Report，失败时回退到 HidD_SetOutputReport。"""
    buf = (ctypes.c_ubyte * len(packet))(*packet)
    event = kernel32.CreateEventW(None, True, False, None)
    if not event:
        raise OSError(f"CreateEventW 失败，错误码: {ctypes.get_last_error()}")

    try:
        ov = OVERLAPPED()
        ov.hEvent = event
        written = wintypes.DWORD(0)

        ok = kernel32.WriteFile(
            handle, ctypes.byref(buf), len(packet), ctypes.byref(written), ctypes.byref(ov)
        )
        if not ok:
            err = ctypes.get_last_error()
            if err == ERROR_IO_PENDING:
                wait_res = kernel32.WaitForSingleObject(event, timeout_ms)
                if wait_res == WAIT_OBJECT_0 and kernel32.GetOverlappedResult(
                    handle, ctypes.byref(ov), ctypes.byref(written), False
                ):
                    return
                kernel32.CancelIoEx(handle, ctypes.byref(ov))
                kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(written), True)

            if hid_dll.HidD_SetOutputReport(handle, ctypes.byref(buf), len(packet)):
                return
            err2 = ctypes.get_last_error()
            raise OSError(err2, f"发送 HID 报文失败 (WriteFile={err}, SetOutputReport={err2})")
    finally:
        kernel32.CloseHandle(event)


def read_report_overlapped(handle: int, report_len: int, timeout_ms: int = 800) -> bytes | None:
    """带超时异步读取一条 HID Input Report，超时后取消 I/O 并返回 None。"""
    buf = (ctypes.c_ubyte * report_len)()
    event = kernel32.CreateEventW(None, True, False, None)
    if not event:
        raise OSError(f"CreateEventW 失败，错误码: {ctypes.get_last_error()}")

    try:
        ov = OVERLAPPED()
        ov.hEvent = event
        bytes_read = wintypes.DWORD(0)

        ok = kernel32.ReadFile(
            handle, ctypes.byref(buf), report_len, ctypes.byref(bytes_read), ctypes.byref(ov)
        )
        if not ok:
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(err, f"ReadFile 失败，错误码: {err}")

            wait_res = kernel32.WaitForSingleObject(event, timeout_ms)
            if wait_res == WAIT_OBJECT_0:
                if not kernel32.GetOverlappedResult(
                    handle, ctypes.byref(ov), ctypes.byref(bytes_read), False
                ):
                    return None
            else:
                kernel32.CancelIoEx(handle, ctypes.byref(ov))
                kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(bytes_read), True)
                return None

        return bytes(buf[: bytes_read.value])
    finally:
        kernel32.CloseHandle(event)


def set_feature_report(handle: int, packet: bytes) -> bool:
    """发送 HID Feature Report。"""
    buf = (ctypes.c_ubyte * len(packet))(*packet)
    return bool(hid_dll.HidD_SetFeature(handle, ctypes.byref(buf), len(packet)))


def get_feature_report(handle: int, report_id: int, length: int) -> bytes | None:
    """读取指定 Report ID 与长度的 HID Feature Report。"""
    if length <= 0:
        return None
    buf = (ctypes.c_ubyte * length)()
    buf[0] = report_id & 0xFF
    if hid_dll.HidD_GetFeature(handle, ctypes.byref(buf), length):
        return bytes(buf)
    return None


# ==============================================================================
# 蓝牙 PnP 电量枚举
# ==============================================================================


def _read_reg_str(dev_info: ctypes.c_void_p, dev_data: SP_DEVINFO_DATA, prop_id: int) -> str:
    """读取 PnP 设备注册表字符串属性。"""
    req = wintypes.DWORD(0)
    setupapi.SetupDiGetDeviceRegistryPropertyW(
        dev_info, ctypes.byref(dev_data), prop_id, None, None, 0, ctypes.byref(req)
    )
    if req.value <= 2:
        return ""
    buf = ctypes.create_unicode_buffer(req.value // 2 + 1)
    if setupapi.SetupDiGetDeviceRegistryPropertyW(
        dev_info,
        ctypes.byref(dev_data),
        prop_id,
        None,
        ctypes.cast(buf, ctypes.c_void_p),
        req.value,
        None,
    ):
        return buf.value.strip()
    return ""


def _read_battery_prop(dev_info: ctypes.c_void_p, dev_data: SP_DEVINFO_DATA) -> int | None:
    """读取 DEVPKEY_Device_BatteryPlusCharging（蓝牙设备电量）。"""
    prop_type = wintypes.ULONG(0)
    req = wintypes.DWORD(0)
    ok = setupapi.SetupDiGetDevicePropertyW(
        dev_info,
        ctypes.byref(dev_data),
        ctypes.byref(DEVPKEY_DEVICE_BATTERY),
        ctypes.byref(prop_type),
        None,
        0,
        ctypes.byref(req),
        0,
    )
    if not ok and ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
        return None
    if req.value == 0:
        return None

    buf = (ctypes.c_ubyte * req.value)()
    if setupapi.SetupDiGetDevicePropertyW(
        dev_info,
        ctypes.byref(dev_data),
        ctypes.byref(DEVPKEY_DEVICE_BATTERY),
        ctypes.byref(prop_type),
        ctypes.byref(buf),
        req.value,
        ctypes.byref(req),
        0,
    ):
        val = int(buf[0])
        if 0 <= val <= 100:
            return val
    return None


def _extract_bt_mac_key(instance_id: str) -> str:
    """从蓝牙 PnP InstanceId 提取稳定设备标识（如 MAC 地址）。"""
    matches = _MAC_RE.findall(instance_id)
    if matches:
        # 蓝牙实例 ID 最后一段或 DEV_ 后通常带有 12 位十六进制 MAC
        for candidate in reversed(matches):
            if candidate.upper() != "000000000000":
                return candidate.lower()
    return instance_id.lower()


def enumerate_pnp_battery_devices() -> list[PnpBatteryDevice]:
    """枚举当前系统所有暴露了 Windows 蓝牙电量属性的无线外设。"""
    dev_info = setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES
    )
    if not dev_info or dev_info == INVALID_HANDLE_VALUE:
        return []

    raw_items: list[PnpBatteryDevice] = []
    # 同一个蓝牙 MAC 可能在 PnP 中有多个节点，缓存有友好名称的节点用于补全 GATT 电池子服务名称
    mac_best_name: dict[str, str] = {}
    mac_best_class: dict[str, str] = {}

    try:
        idx = 0
        dev_data = SP_DEVINFO_DATA()
        dev_data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        id_buf = ctypes.create_unicode_buffer(512)

        while setupapi.SetupDiEnumDeviceInfo(dev_info, idx, ctypes.byref(dev_data)):
            idx += 1
            if not setupapi.SetupDiGetDeviceInstanceIdW(
                dev_info, ctypes.byref(dev_data), id_buf, 512, None
            ):
                continue

            inst_id = id_buf.value
            upper_id = inst_id.upper()
            if not upper_id.startswith(_BT_PREFIXES):
                continue

            mac_key = _extract_bt_mac_key(inst_id)
            friendly = _read_reg_str(dev_info, dev_data, SPDRP_FRIENDLYNAME)
            desc = _read_reg_str(dev_info, dev_data, SPDRP_DEVICEDESC)
            dev_class = _read_reg_str(dev_info, dev_data, SPDRP_CLASS)

            # 记录非通用描述的最佳设备名
            if friendly and mac_key not in mac_best_name:
                mac_best_name[mac_key] = friendly
            elif desc and "GATT" not in desc.upper() and mac_key not in mac_best_name:
                mac_best_name[mac_key] = desc

            if dev_class in ("Mouse", "Keyboard") and mac_key not in mac_best_class:
                mac_best_class[mac_key] = dev_class

            bat = _read_battery_prop(dev_info, dev_data)
            if bat is None:
                continue

            name = friendly or mac_best_name.get(mac_key) or desc or "蓝牙无线设备"
            final_class = mac_best_class.get(mac_key, dev_class)
            raw_items.append(
                PnpBatteryDevice(
                    instance_id=inst_id,
                    mac_key=mac_key,
                    name=name,
                    dev_class=final_class,
                    battery=bat,
                )
            )
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)

    # 二次补全名字和类别（以防电池子节点比主设备节点先枚举到）
    for item in raw_items:
        if (not item.name or "GATT" in item.name.upper() or item.name == "蓝牙无线设备") and item.mac_key in mac_best_name:
            item.name = mac_best_name[item.mac_key]
        if item.dev_class not in ("Mouse", "Keyboard") and item.mac_key in mac_best_class:
            item.dev_class = mac_best_class[item.mac_key]

    return raw_items
