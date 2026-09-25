# 测试与实机验收

## 自动化门禁

运行：

```bash
./script/test.sh
```

门禁依次执行 Ruff format/check、strict mypy 与 pytest/coverage。0.1.2 本机结果为 70 passed，整体覆盖率 89.88%，核心业务模块覆盖率 95%；门槛分别为 80% 与 90%。AppKit 生命周期胶水、UI 和 Keychain 系统绑定不计入核心覆盖率，通过真实打包 UI 检查验证。

0.1.2 新增无硬件副作用的五页深浅色、快速面板截图检查，以及数据状态、缺设备、主题切换、未保存目标保护、真实采样展示／断开清空断言。视觉开发采用内存夹具，不代表实机流量；测试不会发送短信、iMessage 或开启 SIM 数据。0.1.1 的联网实测记录保留，不能当作本版重新执行了联网测试。

GitHub Actions 的既有 `v0.1.0`、`v0.1.1` 发布工作流已通过；tag 工作流在官方 arm64 macOS runner 上重新安装锁定依赖、重跑门禁、生成并发布 DMG。各次运行的最终状态以 GitHub Actions 为准。

### 0.1.2 本机界面验收

- 构建产物直接执行 UI smoke：五页 × 深浅色、原生 NSPopover 的实际打开／关闭与截图均通过，无布局冲突或 traceback。
- 正常启动最终 `.app` 并查看实际窗口：模块 QDC507、中国电信、FDD LTE、当前接口与信号正常显示；数据 OFF，转发未开启。
- 仅截取应用自身窗口核对工具栏、分组卡片、数字和布局，没有收集其他应用画面。
- DMG 只读挂载与卸载、arm64、ad-hoc 签名、Info.plist、SHA-256 检查通过。校验文件使用相对文件名，便于下载后直接校验。
- 本轮没有重新执行收费上网探测、SMS 收发／删除或 iMessage 发送。未公证，不能保证首次安装不出现 Gatekeeper 提示。

覆盖内容包括 AT 分片/URC/prompt/timeout、Unicode/Emoji PDU、8/16-bit multipart、去重、重试、cleanup、SQLite 损坏隔离、AppleScript argv 注入防护、USB endpoint 变化、ECM 重编号、数据确认门、counter reset、日/月流量、设置权限与日志脱敏。

## 构建验证

`./script/build_and_run.sh --build-only` 会先运行全部门禁，再生成 arm64 app、逐个签名 Mach-O、验证 bundle 签名、Info.plist、LSUIElement、bundle identifier 和架构。

`./script/build_and_run.sh --package` 额外生成 DMG，挂载只读验证后输出 SHA-256。

旧版仅检查进程存在，曾漏掉 py2app 启动错误。0.1.1 构建增加实际二进制 `--ui-smoke`：不访问 USB、Keychain 或短信，构造真实菜单及四个设置页，渲染深浅色截图，要求明确完成标记，且不允许 Python traceback 或布局冲突。另执行正常应用启动和界面检查。

## 0.1.1 上网故障与界面验收

- 发现并修复 `(*)` 禁用服务解析错误：它曾把 QDC507 错绑到上一块网卡。
- 删除通用 USB Ethernet 猜测匹配；回归覆盖 en9 普通网卡与 en11 模块并存。
- 禁止普通 AT 连接发送 USB SET_CONFIGURATION，且不探测 CDC 数据接口。
- 修复 DHCP 实际输出 `router (ip_mult)` 的网关解析；无地址/网关时不报成功。
- 发现同时运行的 DJI4GMenuBar 与 AT 辅助进程，已正常退出以隔离测试；应用新增冲突提示。
- 本机 macOS/QDC507 组合中，即使无控制器占用，networksetup 关闭再开启仍可复现 ECM inactive；增加停机等待也未恢复。模块重启后可正常取得地址。
- 新增仅在用户确认开启后的有界恢复，实测从失活状态恢复为 ON，获得模块私网地址和网关，经 en11 完成 HTTPS 200，返回正文约 1 KB，最后验证 OFF。
- 首个 1.1.1.1 HTTP 探测超时；不能把单一探测点失败当成整个 4G 不可用。随后通过绑定 en11、固定服务器地址并校验 TLS 的 HTTPS 请求验证成功。
- 默认路由仍为现有 VPN 的 utun4，Wi-Fi 服务仍第一；这不等于已测试关闭 Wi-Fi 后的 VPN 底层出口切换，该项仍待验收。
- 新界面使用原生 NSTabViewController 工具栏、系统开关、语义色和自动布局；检查四个页面、深浅色和完整原生窗口截图，未见裁切。
- 未发送 iMessage、未读取短信正文、未删除短信。睡眠/唤醒、完整断网切换和短信端到端验收仍未执行。

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
