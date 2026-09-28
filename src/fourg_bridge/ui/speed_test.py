"""Native measurement page; a test never starts on page selection."""

import AppKit
import objc

from fourg_bridge.network.speed_test import SpeedState, TestMode
from fourg_bridge.support.presentation import format_bytes
from fourg_bridge.ui.components import columns, group, label, page, section_title, stack


class SpeedTestPage(AppKit.NSObject):
    def initWithDelegate_(self, delegate):
        self = objc.super(SpeedTestPage, self).init()
        if self is None:
            return None
        self.delegate = delegate
        self.mode = AppKit.NSPopUpButton.alloc().init()
        self.mode.addItemsWithTitles_(["Wi-Fi（不回退到 4G）", "当前网络（含 VPN）", "4G 专项"])
        self.mode.setAccessibilityLabel_("测速网络")
        self.profile = AppKit.NSPopUpButton.alloc().init()
        self.profile.addItemsWithTitles_(["轻量 · 约 10 MiB", "标准 · 约 40 MiB"])
        self.profile.setAccessibilityLabel_("测速流量档位")
        self.start = AppKit.NSButton.buttonWithTitle_target_action_("开始测速…", self, "startTest:")
        self.start.setBezelColor_(AppKit.NSColor.controlAccentColor())
        self.stop = AppKit.NSButton.buttonWithTitle_target_action_("停止", self, "stopTest:")
        self.status = label("准备就绪", 20, weight=AppKit.NSFontWeightSemibold)
        self.route = label("选择网络，了解此刻的连接表现。", 12, True)
        self.progress = AppKit.NSProgressIndicator.alloc().init()
        self.progress.setStyle_(AppKit.NSProgressIndicatorStyleBar)
        self.progress.setIndeterminate_(False)
        self.progress.setMaxValue_(1)
        self.progress.setAccessibilityLabel_("测速阶段进度")
        self.metrics = {}
        cards = []
        for key, title, icon, unit in (
            ("download_mbps", "下载", "arrow.down", "Mbps"),
            ("upload_mbps", "上传", "arrow.up", "Mbps"),
            ("latency_ms", "HTTPS 延迟", "timer", "ms · 三次中位数"),
        ):
            value = label("—", 34, weight=AppKit.NSFontWeightMedium, numeric=True)
            value.setTextColor_(AppKit.NSColor.controlAccentColor())
            self.metrics[key] = value
            cards.append(group([section_title(title, icon), value, label(unit, 12, True)]))
        self.detail = label("尚无测速结果", 12, True)
        self.view = page(
            "网络测速",
            "按需测量，流量消耗始终清楚。",
            [
                group(
                    [
                        section_title("测试你的连接", "speedometer"),
                        stack([self.mode, self.profile], True),
                        stack([self.start, self.stop], True),
                        self.status,
                        self.route,
                        self.progress,
                    ],
                    accent=True,
                ),
                columns(cards),
                group([section_title("本次测量", "chart.bar"), self.detail]),
                group(
                    [
                        section_title("了解结果与隐私", "hand.raised"),
                        label(
                            "测速服务：Cloudflare。只传输随机测试数据，"
                            "不上传短信、文件或 Apple ID；"
                            "服务方可以看到公网 IP。结果仅保留在本次运行内。\n"
                            "Wi-Fi／4G 专项绑定对应网卡，不会自动开启 4G；VPN 仍可能影响连接。"
                            "专项先通过当前系统网络向 Cloudflare 解析测速域名；"
                            "下载／上传固定走所选网卡，不改系统 DNS。"
                            "当前网络模式沿用系统解析。不可达时不切换线路或重试。\n"
                            "单连接有效速率包含连接开销，不代表带宽峰值。HTTPS 延迟为首字节时间，"
                            "不是 ICMP ping；协议开销、其他程序流量不包含在测试有效载荷中。",
                            12,
                            True,
                        ),
                    ]
                ),
            ],
        )
        self.progress.widthAnchor().constraintEqualToAnchor_constant_(
            self.view.documentView().widthAnchor(), -96
        ).setActive_(True)
        self.refresh(SpeedState())
        return self

    @objc.python_method
    def refresh(self, state):
        self.start.setEnabled_(not state.running)
        self.stop.setEnabled_(state.running)
        self.mode.setEnabled_(not state.running)
        self.profile.setEnabled_(not state.running)
        self.status.setStringValue_(state.note)
        self.route.setStringValue_(state.route)
        self.progress.setDoubleValue_(state.progress)
        for name, view in self.metrics.items():
            value = getattr(state, name)
            view.setStringValue_("—" if value is None else f"{value:.1f}")
        jitter = "—" if state.jitter_ms is None else f"{state.jitter_ms:.1f} ms"
        self.detail.setStringValue_(
            f"响应抖动  {jitter}    已完成有效载荷  {format_bytes(state.payload_bytes)}\n"
            + (f"本次耗时 {state.elapsed:.1f} 秒。" if state.elapsed else "等待测量完成。")
            + "取消／失败时可能有未计入的传输，实际用量以运营商为准。"
        )

    def startTest_(self, _sender):
        modes = (TestMode.WIFI, TestMode.CURRENT, TestMode.CELLULAR)
        self.delegate.start_speed_test(
            modes[self.mode.indexOfSelectedItem()], self.profile.indexOfSelectedItem()
        )

    def stopTest_(self, _sender):
        self.delegate.stop_speed_test()
