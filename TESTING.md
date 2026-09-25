# 测试与实机验收

## 自动化门禁

运行：

```bash
./script/test.sh
```

门禁依次执行 Ruff format/check、strict mypy 与 pytest/coverage。当前结果为 50 passed，整体覆盖率 88.96%（四舍五入 89%），核心业务模块覆盖率 95%；门槛分别为 80% 与 90%。AppKit 生命周期胶水、UI 和 Keychain 系统绑定不计入核心覆盖率，通过 `.app` 启动与系统集成检查验证。

GitHub Actions 的 `main` 与 `v0.1.0` 工作流均已通过；tag 工作流在官方 arm64 macOS runner 上重新安装锁定依赖、重跑门禁、生成并发布 DMG。

覆盖内容包括 AT 分片/URC/prompt/timeout、Unicode/Emoji PDU、8/16-bit multipart、去重、重试、cleanup、SQLite 损坏隔离、AppleScript argv 注入防护、USB endpoint 变化、ECM 重编号、数据确认门、counter reset、日/月流量、设置权限与日志脱敏。

## 构建验证

`./script/build_and_run.sh --build-only` 会先运行全部门禁，再生成 arm64 app、逐个签名 Mach-O、验证 bundle 签名、Info.plist、LSUIElement、bundle identifier 和架构。

`./script/build_and_run.sh --package` 额外生成 DMG，挂载只读验证后输出 SHA-256。

本机安全启动测试已在未插 QDC507 时执行：进程保持运行、菜单栏 app 以 UIElement 注册，没有 Python traceback 或崩溃。系统 AppIntents 服务在当前 macOS 预览系统上输出非致命注册噪声，不影响应用运行。

## 2026-09-25 QDC507 实机结果

- USB：`2C7C:0125`，制造商 `BAIWANG`，产品 `EG25G-QDC507`。
- 固件标识：`QDC507GLEFM21`；USB 网络模式为 ECM (`usbnet=1`)。
- SIM：`READY`；运营商 `CHN-CT`；注册状态 `registered_home`；RAT `FDD LTE`。
- 信号：`CSQ 20`，换算约 `-73 dBm`。
- 当前 ECM 接口动态识别为 `en11`，网络服务为 `EG25G-QDC507 2`；同时存在普通 USB 网卡 `en9`，已验证不会再被误判为 QDC507。
- 应用启动后 QDC507 网络服务处于禁用状态；Wi-Fi 保持服务顺序第一，实际公网路由保持现有 VPN 的 `utun4`，没有修改 DNS、静态路由或其他服务相对顺序。
- 修复并验证两个真实产物启动问题：PyObjC 内部方法 selector 误解析、错误的睡眠通知常量。修复后的 ad-hoc arm64 `.app` 连续运行超过十分钟，无 traceback 或启动器弹窗。
- 短信转发设置保持关闭；未读取短信正文、未发送 iMessage、未删除模块短信，也未执行 4G 数据 ON 测试。

## 实机测试顺序

1. 不插模块启动，确认无崩溃且数据 OFF。
2. 插入模块，只读检查 VID/PID、AT endpoint、SIM、运营商、注册和信号。
3. 拔出并重插，确认旧 session 释放，endpoint 和 ECM 接口重新发现。
4. 分别测试未插 SIM、未注册、无信号和 AT timeout。
5. 保持 Wi-Fi 与 VPN，确认 Wi-Fi 始终是默认接口，VPN 与其他服务相对顺序不变。
6. 睡眠/唤醒后确认数据 OFF。
7. 取得明确确认后测试数据 ON/OFF；记录前后 network service 与 `CGATT`。
8. 取得明确确认后发送固定 iMessage 测试文本。
9. 取得明确确认后接收专用测试短信，验证成功后才删除模块短信。

任何收费、发送或删除动作都不是自动化测试的一部分。
