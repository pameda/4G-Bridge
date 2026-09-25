# 4G Bridge 架构

## V1.2 界面分层

`ui/components.py` 提供原生布局、语义色、SF Symbols 和速度图；`ui/status_panel.py` 是菜单栏快速面板；`ui/settings_window.py` 组织总览、流量、短信转发、设备和设置。无副作用的展示规则与短期内存采样位于 `support/presentation.py`，可独立测试。ApplicationController 在主线程发布已采集的数据；视图不会直接探测设备、读取短信或更改网络。

外观偏好以可向后兼容的 `appearance` 字段持久化，数据开启状态仍不持久化。图表只消费真实 interface counters；无样本为缺测，不虚构套餐百分比、功耗、温度或应用用量。

## 原则

核心逻辑与 AppKit 分离。USB、AT、Messages、网络命令、Keychain 与 SQLite 都有窄接口，硬件不可用时仍能进行确定性测试。后台线程不得直接更新 UI，所有结果回到 AppKit 主线程。

```text
QDC507 USB
  └─ USBDiscovery → USBSessionFactory → ATTransport
       ├─ ModemController → SIM / 注册 / 信号 / RAT
       ├─ SMSReceiver → PDUDecoder → SMSAssembler
       │    └─ SMSRelay → RelayDatabase → MessagesBridge → Messages.app
       └─ DataSessionManager → ECM 网络服务 / CGATT 回退

macOS 网络
  └─ ECMDetector → TrafficMonitor → TrafficLedger → MenuBar
```

## 模块职责

- `modem/`：VID/PID 发现、动态 endpoint 扫描、唯一 USB 读线程、AT parser 与 modem snapshot。
- `cellular/`：networksetup 服务开关与 `CGATT` 安全回退。
- `sms/`：PDU 解码、多段乱序组装、稳定 SHA-256 去重、重试与成功后清理。
- `imessage/`：固定 AppleScript、argv 传参、iMessage service/participant 检查与错误映射。
- `network/`：ECM 接口、默认路由、VPN 存在性、接口 counters 和日/月聚合。
- `storage/`：版本化 relay SQLite、原子偏好和 Keychain 目标。
- `ui/`：菜单栏与设置窗口；不包含业务状态机。
- `app/`：生命周期、热插拔、睡眠/唤醒、安全 OFF 与主线程调度。

## SMS 一致性

状态流为：

```text
pending → sending → sent
                  ↘ cleanup_pending → sent
        ↘ retry → sending
        ↘ failed
sending（进程崩溃）→ delivery_unknown
```

发送前将状态写为 `sending`。如果进程在 Messages 已接受消息后、数据库确认前崩溃，重启后进入 `delivery_unknown`，不会自动重发。Messages 成功但模块删除失败则进入 `cleanup_pending`，以后只执行 `AT+CMGD`。

去重材料是规范化 sender、SCTS 时间和按顺序排列的原始 PDU。SQLite 不保存正文；重启后正文从仍留在 QDC507 的 PDU 重新构建。

## 数据安全状态

内存中的 data state 从不持久化。启动时为 OFF。ECM 服务被明确识别后，OFF 首先禁用该服务并验证；只有失败时才使用 `CGATT=0`。ON 需要 UI 明确确认。若 QDC507 排在 Wi-Fi 前，仅将 QDC507 移到 Wi-Fi 后，保留其他服务相对顺序。允许现有 utun VPN 默认路由，不接管 VPN 配置。

开启在后台执行，等待有效 IPv4 和 DHCP 网关；失败回退 OFF。QDC507/macOS ECM 在服务关闭后有时无法恢复，只有此次明确确认的 ON 请求可以尝试一次 `AT+CFUN=1,1`，释放旧会话并在有界时间内重新枚举，先绑定安全 OFF，再完成用户的开启请求。普通扫描、热插拔和应用启动均不走这条自动开启路径。V1 不修改 DNS 或静态路由。

## 权限

- Apple Events / Automation：仅控制 `com.apple.MobileSMS`。
- Keychain：存储单一 iMessage 目标。
- 不申请 Accessibility、Full Disk Access、Network Extension 或 DriverKit 权限。
- App 不启用 App Sandbox，因为 libusb 需要访问用户连接的 USB 设备；仍保持最小功能边界。

## 参考项目与 clean-room 约束

`HD838A/dji-4g-mac` 未发现源码许可证；Gitee 发布项目只有发行物且无源码许可。因此本项目只采用公开可观察的 VID/PID、AT 行为和 macOS 交互事实，不复制源码、图标、名称或品牌素材。
