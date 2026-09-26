# 4G Bridge 架构

## 0.1.13 / Windows preview.3 安全与切网

- Mac `ScopedCarrierBudget` 使用安装内随机密钥生成 SIM HMAC，身份失效即撤销本次授权；首次绑定只接收绑定时间之后的套餐回复。旧无归属账本不导入，SIM 切换重建 counter 基线，不清除已有用量或锁定。
- Relay schema 2 增加逐段 `CleanupProof`（存储区、序号、PDU hash、设备＋SIM HMAC）。`delete_verified` 返回 deleted / pending / blocked；AT 组合事务锁保护身份查询、全量列表核验和单槽删除。blocked 不自动重试删除或重发，旧记录无凭据默认 blocked。此锁只约束本应用，不能保证对抗其他控制器或模块固件的并发修改，因此要求独占使用模块。
- 转发 SQLite 升级前使用 backup API；新版本库只读检查后拒绝打开，损坏时保留完整文件组并阻断写入，不新建空库继续发送。UI 可继续展示网络功能。
- 固定 AppleScript 通过 Foundation 读取 JSON 标准输入，目标／正文不进入 argv 或临时文件；超时继续作为投递不确定处理。
- Windows 系统接口通知和 WLAN ACM 通知只唤醒检测线程，250ms 合并事件、2秒轮询兜底；不请求定位。单独 spawn 进程承载 DNS/TLS/HTTP，6秒整轮 deadline，退出／网络代际变化时终止回收。冻结 EXE 在创建窗口和互斥锁前执行 freeze_support。
- Windows 长时间网络切换使用独立 transition 锁，不阻塞 counter 计量锁；关闭操作和额度守卫可设置开启取消标记，提交成功前再次核验授权／额度／SIM。UI 与中文日志共用固定原因目录，原始异常不进入日志。

## Windows 预览版平台边界

`windows/` 为独立入口，不导入 macOS AppKit／Messages UI。`native.py` 封装系统 COM 和 GetIfEntry2；`platform.py` 以固定 PowerShell 脚本做设备发现和 GUID＋VID/PID 双重核验的网卡操作。`metric.py` 保存模块 IPv4 metric 租约，在关闭及下次启动恢复，绝不覆盖无关接口。

`runtime.py` 分离网卡发现、AT／运营商短信和约一秒流量守卫线程。`policy.py` 是可测试的自动接管规则；`probe.py` 用 Windows IP_UNICAST_IF 将 TLS 探测绑定 Wi-Fi 出口，不仅绑定源地址。`ui.py` 仅在 Tk 主线程更新，后台通过队列交付；`tray.py` 处理系统托盘和电源事件。`settings.py` 保存非敏感偏好及当前用户登录项，数据开启与 80% 授权不持久化。

复用 `modem/at_transport.py`、`sms/` 解码与组装、`cellular/carrier_query.py`、`storage/carrier_budget.py`、流量账本和安全日志。Windows 只提取运营商数值，不调用 SMS 删除或转发；SIM ICCID 仅在内存中生成哈希后关联独立账本，不持久化原文。查询绑定确认时的 SIM 哈希且 60 秒后失效，不在断线恢复后意外发送。

Windows Python 运行部分没有新增第三方依赖。Tk/ttk 控件来自官方 Python 的 Tcl-Tk；打包工具另设固定版本、哈希及人工授权步骤，不影响 macOS 依赖锁或已安装应用。

## V1.2 界面分层

`ui/components.py` 提供原生布局、语义色、SF Symbols 和速度图；`ui/status_panel.py` 是菜单栏快速面板；`ui/settings_window.py` 组织总览、流量、短信转发、设备和设置。无副作用的展示规则与短期内存采样位于 `support/presentation.py`，可独立测试。ApplicationController 在主线程发布已采集的数据；视图不会直接探测设备、读取短信或更改网络。

外观偏好以可向后兼容的 `appearance` 字段持久化，数据开启状态仍不持久化。图表只消费真实 interface counters；无样本为缺测，不虚构套餐百分比、功耗、温度或应用用量。

## 原则

### 0.1.9 新增边界

`network/app_traffic.py` 仅读取系统进程字节汇总，在可见界面期间采样；UI 负责本机图标和名称解析。计数跨中断重建基线，累计不持久化，不进行物理出口推断。

`cellular/carrier_query.py` 提供白名单服务号、严格短指令验证、PDU 单次提交及保守套餐解析。`ModemRuntime` 使用现有独占 AT 通道，查询 10 分钟内防重复；回复在关闭转发时可解析但不删除。`ui/usage_ring.py` 仅消费明确的运营商总量／已用量，与本地计费保护独立。

`app/login_item.py` 是系统 SMAppService 的窄桥接；`support/event_log.py` 只接受固定代码映射的中文事件，不接受自由文本或设备原始输出。8 个原生页面共享主线程快照，菜单可滚动以适配小屏幕。

`storage/carrier_budget.py` 维护独立套餐保护：运营商总量／已用、时间、累计计数、98% 锁定均持久化，无正文。80% 同意仅存在内存，连接关闭／睡眠／重启清除；未知、6 小时过期或跨月旧快照停止。独立守卫线程先关闭网络，80% 处主线程弹窗；98% 不允许本地固定额度覆盖。新月完整查询可重新判定。同月更新保守取已有估算与新回复的较高用量。

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
- `imessage/`：固定 AppleScript、标准输入 JSON 传参、iMessage service/participant 检查与错误映射。
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

### 0.1.4 授权式自动接管扩展

原先的 OFF 默认值保留。用户保存有限额度并授权后，启动／重插／唤醒先安全关闭，再由独立策略重新确认 Wi-Fi 状态。`network/failover.py` 是无副作用状态机，三次失败开启、两次成功关闭，VPN／其他默认网络存在时暂缓。开启时临时只将 QDC507 移到 Wi-Fi 前，回退时恢复 Wi-Fi 优先，所有无关服务相对顺序保持不变。授权说明包含必要时一次 CFUN 有界恢复，失败后暂停，不循环重启。恢复期间仅在确认网络服务关闭时容忍临时缺少 counters，否则计量异常仍执行安全关闭。

`storage/budget.py` 的版本独立 SQLite 表仅保存用量、锁定位、月份、接口与开机期计数。锁定在关闭命令前持久化。普通设置修改、进程重启、重插和月份变化不清除锁定位；唯有手动确认的 grant 开启下一份有限额度。`app/auto_data.py` 将约 1 秒的计量保护与较慢的 Wi-Fi 检查分为线程，不经过短信锁；到顶先关闭 ECM，再交还运行时执行安全关闭及回退。

这是用户态采样保护，不是运营商硬限额，可能因系统调用／采样延迟超额。计量错误不能授权开启。独立 daily/monthly ledger 不因手动追加额度而清零。

### 系统权限

- Apple Events / Automation：仅控制 `com.apple.MobileSMS`。
- Keychain：存储单一 iMessage 目标。
- 不申请 Accessibility、Full Disk Access、Network Extension 或 DriverKit 权限。
- App 不启用 App Sandbox，因为 libusb 需要访问用户连接的 USB 设备；仍保持最小功能边界。

## 参考项目与 clean-room 约束

`HD838A/dji-4g-mac` 未发现源码许可证；Gitee 发布项目只有发行物且无源码许可。因此本项目只采用公开可观察的 VID/PID、AT 行为和 macOS 交互事实，不复制源码、图标、名称或品牌素材。
