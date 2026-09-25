# 4G Bridge

4G Bridge 是面向 Apple Silicon Mac 与 DJI / Baiwang QDC507 的原生菜单栏工具。它读取模块中的 SMS，在成功组装与去重后，通过 macOS Messages AppleScript 接口将内容发送给用户指定的 iMessage 目标。

## 当前能力

- 识别 `2CA3:4006` 与 `2C7C:0125`，每次连接重新扫描 USB bulk endpoint。
- 单一 AT 工作线程，串行 transaction，并将 `+CMTI` 等 URC 与普通响应分流。
- 读取 SIM、运营商、LTE 注册、RAT、CSQ/RSSI 与 ECM 网络信息。
- 支持 GSM 7-bit、扩展字符、UCS-2/UTF-16BE、Emoji 与 8/16-bit multipart UDH。
- Messages 正文只通过 `osascript` argv 传递，不拼入脚本，也不读写 `chat.db`。
- SQLite 只保存 hash、脱敏所需元数据、状态、重试次数和模块位置，不保存正文。
- 失败按 1、5、15 分钟重试；成功后才删除模块短信；删除失败只重试清理。
- 数据默认 OFF；启动、USB 重连、睡眠、唤醒与正常退出均执行安全关闭。
- 动态发现 ECM `enX` 与网络服务；从接口 counters 统计速度、本次、今日和本月流量。
- Wi‑Fi 与 4G 同时连接时强制保持 Wi‑Fi 默认路由；校验失败会回滚关闭 4G。
- 原生 AppKit、SF Symbols、语义色、深浅色适配；无 Dock 图标、无 WebView。

## 安装

1. 打开 `artifacts/4G-Bridge-0.1.0-arm64.dmg`。
2. 将 4G Bridge 拖到“应用程序”。
3. 首次启动若 Gatekeeper 提示，在“系统设置 → 隐私与安全性”中确认打开。
4. 在设置中填写手机号或 Apple ID，保存到 macOS 钥匙串。
5. 只有点击“发送测试消息”或真实短信需要转发时，系统才会请求 Automation 权限。

这是 ad-hoc 签名、未公证的 V1 构建；它不申请 Accessibility、Full Disk Access，不要求关闭 SIP，也不安装内核驱动。

## 开发

```bash
./script/bootstrap.sh
./script/test.sh
./script/build_and_run.sh
./script/build_and_run.sh --package
```

Codex Run 按钮已绑定到 `script/build_and_run.sh`。依赖由 `requirements-arm64.lock` 固定版本与 SHA-256，并仅从官方 PyPI 安装。

## 安全边界

- 不修改 Messages 数据库，不伪造入站消息。
- 不存储短信正文，不在日志中记录完整手机号、ICCID 或 Apple ID。
- 不抓包，不做 DPI，不记录域名、目标 IP 或应用流量。
- 不保存 Apple ID 密码或 Token。
- 不自动开启 SIM 数据；开启前必须由用户明确确认。
- 不改 DNS、静态路由、VPN 配置或无关网络服务顺序。
- 仅在 QDC507 排在 Wi‑Fi 前时做最小顺序调整，并在开启后再次核验默认路由。

本仓库当前为私有工程，第一方源码未授予公开复用许可证。第三方组件许可见 `THIRD_PARTY_NOTICES.md`。
