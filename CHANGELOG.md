# Changelog

## 0.1.1 — 2026-09-25

- 重做设置窗口：原生工具栏、连接状态分组、系统开关、对齐的信息行和深浅色界面；菜单精简，技术详情移到子菜单。
- 修复 macOS 禁用服务的 `(*)` 解析错误，避免错误控制上一块网卡；删除通用 USB Ethernet 猜测匹配。
- 避免 AT 会话重设整个 USB 设备配置，排除 CDC ECM 数据接口；避免重复执行蜂窝附着。
- 支持真实 DHCP 的 `router (ip_mult)` 格式，开启时等待 IP/网关，失败回退关闭并展示原因。
- 数据开关移至后台，界面显示连接进度；仅移动 QDC507 服务以保留其他网络服务相对顺序。
- 针对实机 ECM 关闭后无法恢复的问题，增加用户确认开启流程内的一次有界模块重启；轮询、启动和重连不会自动开启。
- 提示退出同时运行的 DJI 控制器。构建必须执行真实打包 UI 的四页深浅色检查，避免仅凭进程存在误报启动成功。

## 0.1.0 — 2026-09-25

- 建立 clean-room Python/PyObjC 菜单栏应用。
- 添加 QDC507 双 VID/PID、动态 bulk endpoint 与单 AT reader worker。
- 添加 SIM/LTE/信号快照和动态 ECM 网络发现。
- 添加 GSM 7-bit、UCS-2/UTF-16BE、Emoji 与 multipart SMS 管线。
- 添加最小 SQLite relay 状态、去重、退避、delivery unknown 与 cleanup pending。
- 添加 Messages AppleScript argv bridge 与明确错误映射。
- 添加安全数据 OFF/ON 状态机与接口 counter 流量统计。
- 添加原生中文菜单栏和设置窗口、Keychain 目标存储。
- 添加 arm64 py2app、ad-hoc 签名、DMG 和 GitHub Actions 工作流。
- 添加 49 项自动化测试，整体覆盖率 89.00%，核心业务模块覆盖率 95%。
- 修正注册查询响应与同名 URC 的分流，补充 ATI、QCFG、QCCID、CNUM 与三级注册状态读取。
- 设置页增加模块网络详情和 `delivery_unknown` 人工重试/确认入口。
- py2app 明确排除未使用的 Tcl/Tk，缩小 App 并提高远端签名可复现性。
- Wi‑Fi 与 4G 共存时保持 Wi‑Fi 默认路由，验证失败自动回滚关闭 4G。
- 修复打包应用中 PyObjC 将菜单内部方法误解析为 selector 导致的启动失败。
- 使用正确的 macOS 睡眠通知并通过真实 `.app` 启动验证。
- 优先匹配 Baiwang/QDC507/EC25/EG25G，避免把普通 USB 网卡误识别为模块 ECM 接口。
- 完成 QDC507 `2C7C:0125` 实机只读验收；自动化测试增至 50 项。
