# -*- coding: utf-8 -*-
"""无线外设电量监控单元测试（覆盖 Compx、罗技 HID++、雷蛇、蓝牙及多设备模型）。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from wireless_battery.config import AppConfig, load_config, save_config
from wireless_battery.hid_win import PnpBatteryDevice
from wireless_battery.models import BatteryStore, DeviceState, LowBatteryTracker
from wireless_battery.protocols import (
    PollResult,
    build_hidpp_long_packet,
    build_keyboard_query_packet,
    build_mouse_query_packet,
    build_razer_feature_packet,
    deduplicate_bluetooth_devices,
    infer_bluetooth_kind,
    is_hidpp_error,
    parse_hidpp_battery_status,
    parse_hidpp_battery_voltage,
    parse_hidpp_unified_battery,
    parse_keyboard_response,
    parse_mouse_response,
    parse_razer_battery_response,
    parse_razer_charging_response,
    voltage_mv_to_percent,
)


class ProtocolAndModelTests(unittest.TestCase):
    """覆盖多品牌协议解析、休眠缓存、低电量防抖与配置向下兼容。"""

    def test_compx_packets_and_responses(self) -> None:
        m_pkt = build_mouse_query_packet()
        self.assertEqual(len(m_pkt), 17)
        self.assertEqual(m_pkt[16], 0x49)
        self.assertEqual(build_mouse_query_packet(0x4D)[16], 0x41)

        k_pkt = build_keyboard_query_packet()
        self.assertEqual(len(k_pkt), 20)
        self.assertEqual(k_pkt[19], 0x5E)

        # Compx 鼠标在线响应
        online_resp = bytes(
            [0x08, 0x04, 0x00, 0x00, 0x00, 0x02, 0x5F, 0x00, 0x0F, 0xF6] + [0x00] * 6 + [0xE3]
        )
        res = parse_mouse_response(online_resp)
        assert res is not None
        self.assertTrue(res.online)
        self.assertEqual(res.battery, 95)
        self.assertEqual(res.voltage_mv, 4086)
        self.assertEqual(res.protocol, "Compx 2.4G")

        # 校验错误 NACK 帧应返回 None
        nack_resp = bytes([0x08, 0x04, 0x01] + [0x00] * 13 + [0x48])
        self.assertIsNone(parse_mouse_response(nack_resp))

        # 真正休眠帧
        sleep_resp = bytes([0x08, 0x04, 0x00] + [0x00] * 13 + [0x49])
        res_sleep = parse_mouse_response(sleep_resp)
        assert res_sleep is not None
        self.assertFalse(res_sleep.online)

        # Compx 键盘在线响应
        kb_resp = bytes([0x13, 0x4A, 0x01, 0x00, 0x02, 0x64, 0x01] + [0x00] * 12 + [0xC5])
        kb_res = parse_keyboard_response(kb_resp)
        assert kb_res is not None
        self.assertEqual(kb_res.battery, 100)
        self.assertEqual(kb_res.status_flag, 0x01)

    def test_logitech_hidpp_protocols(self) -> None:
        pkt = build_hidpp_long_packet(dev_idx=0x01, feat_idx=0x05, func_id=0x01)
        self.assertEqual(len(pkt), 20)
        self.assertEqual(pkt[:4], bytes([0x11, 0x01, 0x05, 0x1A]))

        # 错误帧判定
        self.assertTrue(is_hidpp_error(bytes([0x11, 0x01, 0x8F, 0x00, 0x00, 0x00, 0x00])))
        self.assertTrue(is_hidpp_error(bytes([0x10, 0x01, 0xFF, 0x00, 0x00, 0x00, 0x00])))

        # 0x1004 Unified Battery（放电 82%）
        u_resp = bytes([0x11, 0x01, 0x05, 0x1A, 82, 20, 0] + [0] * 13)
        self.assertEqual(parse_hidpp_unified_battery(u_resp), (82, False))

        # 0x1004 充电中
        u_chg = bytes([0x11, 0x01, 0x05, 0x1A, 64, 20, 1] + [0] * 13)
        self.assertEqual(parse_hidpp_unified_battery(u_chg), (64, True))

        # 0x1000 Battery Status
        s_resp = bytes([0x11, 0x01, 0x04, 0x0A, 50, 20, 3] + [0] * 13)
        self.assertEqual(parse_hidpp_battery_status(s_resp), (50, True))

        # 0x1001 Battery Voltage (4000 mV -> 约 70%)
        v_resp = bytes([0x11, 0x01, 0x04, 0x0A, 0x0F, 0xA0, 0x00] + [0] * 13)
        parsed_v = parse_hidpp_battery_voltage(v_resp)
        assert parsed_v is not None
        self.assertEqual(parsed_v[1], 4000)
        self.assertEqual(parsed_v[0], voltage_mv_to_percent(4000))
        self.assertFalse(parsed_v[2])

    def test_razer_90byte_protocol(self) -> None:
        pkt = build_razer_feature_packet(0x07, 0x80, transaction_id=0x1F, args=b"\x00\x00")
        self.assertEqual(len(pkt), 90)
        self.assertEqual(pkt[1], 0x1F)
        self.assertEqual(pkt[5], 0x02)
        self.assertEqual(pkt[6], 0x07)
        self.assertEqual(pkt[7], 0x80)
        # XOR(pkt[2:88]) == 0x02 ^ 0x07 ^ 0x80 == 0x85
        self.assertEqual(pkt[88], 0x85)

        bat_resp = bytearray(90)
        bat_resp[0] = 0x02
        bat_resp[6] = 0x07
        bat_resp[7] = 0x80
        bat_resp[9] = 204  # 204/255 ≈ 80%
        self.assertEqual(parse_razer_battery_response(bytes(bat_resp)), 80)

        chg_resp = bytearray(90)
        chg_resp[0] = 0x02
        chg_resp[6] = 0x07
        chg_resp[7] = 0x84
        chg_resp[9] = 0x01
        self.assertTrue(parse_razer_charging_response(bytes(chg_resp)))

    def test_bluetooth_inference_and_deduplication(self) -> None:
        self.assertEqual(infer_bluetooth_kind("MX Master 3S", "Mouse"), "mouse")
        self.assertEqual(infer_bluetooth_kind("Keychron K2 Pro", ""), "keyboard")
        self.assertEqual(infer_bluetooth_kind("Unknown Gadget", ""), "other")

        dup_list = [
            PnpBatteryDevice(
                instance_id="BTHLEDEVICE\\{0000180F}_AABBCCDDEEFF",
                mac_key="aabbccddeeff",
                name="Bluetooth Low Energy GATT compliant HID device",
                dev_class="HIDClass",
                battery=85,
            ),
            PnpBatteryDevice(
                instance_id="BTHLE\\DEV_AABBCCDDEEFF",
                mac_key="aabbccddeeff",
                name="NuPhy Air75 V2",
                dev_class="Keyboard",
                battery=85,
            ),
        ]
        deduped = deduplicate_bluetooth_devices(dup_list)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].name, "NuPhy Air75 V2")

    def test_multidevice_store_and_alias_backward_compat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            store = BatteryStore(state_path=state_path)
            store.apply_poll_results(
                [
                    PollResult(
                        device_key="keyboard_3554_fa09",
                        default_name="2.4G 无线键盘",
                        kind="keyboard",
                        vid=0x3554,
                        pid=0xFA09,
                        connected=True,
                        online=True,
                        battery=100,
                        connection_type="2.4G",
                        protocol="Compx 2.4G",
                    ),
                    PollResult(
                        device_key="mouse_3554_fb3e",
                        default_name="VGN DragonFly F2 Pro Max",
                        kind="mouse",
                        vid=0x3554,
                        pid=0xFB3E,
                        connected=True,
                        online=True,
                        battery=95,
                        voltage_mv=4081,
                        connection_type="2.4G",
                        protocol="Compx 2.4G",
                    ),
                ],
                now_ts=1000.0,
            )

            ordered = store.get_ordered_devices()
            self.assertEqual([d.kind for d in ordered], ["mouse", "keyboard"])

            # 模拟拔掉键盘接收器：键盘应标为 disconnected，鼠标进入休眠仍保留 95%
            store.apply_poll_results(
                [
                    PollResult(
                        device_key="mouse_3554_fb3e",
                        default_name="VGN DragonFly F2 Pro Max",
                        kind="mouse",
                        vid=0x3554,
                        pid=0xFB3E,
                        connected=True,
                        online=False,
                    )
                ],
                now_ts=1100.0,
            )
            self.assertEqual(store.states["mouse_3554_fb3e"].battery, 95)
            self.assertEqual(store.states["mouse_3554_fb3e"].status, "sleeping")
            self.assertEqual(store.states["keyboard_3554_fa09"].status, "disconnected")
            self.assertEqual(store.clear_disconnected_devices(), 1)
            self.assertNotIn("keyboard_3554_fa09", store.states)

            # 旧配置 mouse_alias / keyboard_alias 向下兼容
            cfg_path = Path(tmp) / "config.json"
            cfg_path.write_text(
                '{"mouse_alias": "VGN F2 Pro Max", "keyboard_alias": "Story65 R3"}',
                encoding="utf-8",
            )
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.alias_for("mouse_3554_fb3e", "mouse", "fallback"), "VGN F2 Pro Max")
            self.assertEqual(cfg.alias_for("keyboard_3554_fa09", "keyboard", "fallback"), "Story65 R3")
            self.assertEqual(cfg.alias_for("logi_046d_c548_01", "mouse", "GPW"), "GPW")

            cfg.device_aliases["logi_046d_c548_01"] = "狗屁王二代"
            save_config(cfg, cfg_path)
            cfg2 = load_config(cfg_path)
            self.assertEqual(cfg2.alias_for("logi_046d_c548_01", "mouse", "GPW"), "狗屁王二代")

    def test_low_battery_tracker_hysteresis(self) -> None:
        tracker = LowBatteryTracker(hysteresis=5)
        st = DeviceState(
            device_key="mouse_1",
            default_name="Mouse",
            kind="mouse",
            vid=0x3554,
            pid=0xFB3E,
            status="online",
            battery=20,
            is_cached=False,
            charging=False,
        )
        self.assertTrue(tracker.check(st, enabled=True, threshold=20))
        st.battery = 18
        self.assertFalse(tracker.check(st, enabled=True, threshold=20))
        st.battery = 25
        self.assertFalse(tracker.check(st, enabled=True, threshold=20))
        st.battery = 19
        self.assertTrue(tracker.check(st, enabled=True, threshold=20))


if __name__ == "__main__":
    unittest.main()
