# Changelog

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
