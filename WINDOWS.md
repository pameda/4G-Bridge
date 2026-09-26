# 4G Bridge Windows 预览版

版本：0.2.0-preview.3。目标 Windows 11 x64。**不包含 iMessage、Apple 账号登录或短信转发功能。**

这是新的平台适配，不能用 macOS 实机结果证明 Windows 硬件兼容。Windows QDC507 实机验收尚未执行；自动测试与 Windows 构建结果见 GitHub Actions 的 Windows preview 工作流。

## 安装与使用

从 [Windows 预览版发布页](https://github.com/pameda/4G-Bridge/releases/tag/windows-v0.2.0-preview.3) 下载 `4G-Bridge-0.2.0-preview.3-windows-x64-setup.exe` 或便携 ZIP，并核对同页的 `windows-SHA256SUMS.txt`。尚未签名，可能出现 SmartScreen 提示，不应关闭系统安全保护。安装器安装到当前用户的应用目录，不安装驱动，不默认注册登录启动。更新前从托盘退出旧版；卸载保留设置及流量锁定记录，避免重新安装绕过保护。

历史 preview.2 的 [构建记录](https://github.com/pameda/4G-Bridge/actions/runs/36247144257) 和 [测试说明](docs/windows-preview-2-release.md) 保留追溯；preview.3 验证以本版发布页为准。云端检查不代替 Windows 11 或 QDC507 实机验收。

1. 安装并启动，接入 QDC507，关闭其他占用模块的控制软件。
2. 先查看“设备”页，确认系统网卡与 AT 串口已就绪。只匹配 `2CA3:4006` / `2C7C:0125`；没有兼容网卡或有多个模块时不猜测控制目标。
3. 首次默认只读。需要数据开关、自动接管时，在“设置”主动选择以管理员权限重新启动；Windows 正常请求 UAC，不绕过权限。
4. “运营商与流量”确认后查询一次。电信预填 10001 / 108，其他地区或运营商必须核实指令；可能收费。不自动重试或定时发送。
5. 取得有效套餐快照后，可手动开启或授权 Wi-Fi 故障自动接管。SIM 身份无法验证时不启用；不同 SIM 使用独立哈希关联的数值记录，不保存 ICCID 原文。

关闭窗口保留系统托盘，单击托盘打开窗口；托盘失败则保留任务栏窗口。退出会先尝试关闭数据，无法确认时警告，不伪称已关闭。

## 功能与边界

- preview.3：系统接口／Wi-Fi ACM 事件唤醒检测，250ms 合并通知并保留2秒轮询，不请求定位；DNS/TLS/HTTP 由独立进程执行，整轮6秒超时，网络变化／关闭／睡眠时取消。计量锁不再被长时间网卡命令占用，开启成功前再次检查额度和取消标记。
- 中文诊断区明确显示权限、SIM、注册、套餐、地址与探测原因；与内存日志共用固定文案，不展示私有原始错误。物理断开只缩短检测等待，仍需驱动、路由和 DHCP 就绪，不能承诺无缝切换。

- 中文总览、运营商与流量、设备、应用网络、运行日志、设置六页；系统主题控件、浅深色、蓝色信号图标及套餐环形图。
- 总览突出套餐估算已用百分比；环形图与百分比同色：低于 60% 蓝色、60% 起橙色、75% 起红色预警。明确标记当前所在的低于 80%、80% 至 98%、达到 98% 区间；未知数据不显示为 0%。预警颜色不改变实际保护状态，过期／锁定状态另行展示。
- Windows 系统 COM AT 通道，不使用 macOS USB 后端、不改 USB personality；QDC507 当前模式是否暴露可用串口和网卡必须实机确认。无适用驱动时明确提示，不自动安装社区驱动。
- Wi-Fi 物理断开走快速接管；仍连接但网络失败需连续三轮确认，恢复连续两轮后关闭自动接管的数据。包含系统枚举、探测及 DHCP 延迟，不保证瞬时或无缝。
- 仅临时调整模块 IPv4 metric；原值先落盘，关闭及下次启动尝试恢复。保留 Wi-Fi、VPN、DNS、其他网卡及路由配置。失败时回滚并暂停，不反复重启。IPv6 接管、第三方 VPN 底层迁移未验收，不宣称支持所有拓扑。
- 流量计量使用系统 64 位接口 counters，独立于短信线程。套餐估算低于 80% 允许使用；80% 需对本次连接确认；98% 持久化锁定。同月查询不会降低既有用量或清锁。六小时过期、计量失效或 SIM 不明时保护性关闭。
- 套餐估算不是实时账单，其他设备使用 SIM、共享套餐、运营商延迟、进程崩溃或系统休眠仍可能造成差异；不得把 98% 当成运营商保证的硬限额。
- 应用网络使用系统 EStats，按进程汇总 **IPv4 TCP** 字节，仅页面可见时采样；不包含 UDP、QUIC、IPv6，短连接可能漏采，代理／本地回环可能重复计数。需要管理员权限。没有数据时提示原因，不填假数据；不记录连接地址或长期历史。
- 运营商 SMS 只在内存中解码、组装并提取必要数值。不转发、不展示短信会话、不自动删除任何短信。模块存储满时需自行管理；Windows 版不能沿用 Mac 的“转发后清理”。
- 中文日志仅内存最近 500 条，不保存短信正文、手机号、ICCID、Apple ID、IP、原始异常。普通设置及数值账本位于当前用户 `%LOCALAPPDATA%\4G Bridge`，继承用户目录 ACL。
- 登录启动为当前用户 Run 项，只有主动开关才设置；不会绕过 UAC、创建计划任务或常驻系统服务。登录后无管理员权限时不自动接管。
- 默认 OFF；启动、重连、重新检测、睡眠事件、唤醒及正常退出执行安全关闭。断电、强杀、睡眠截止时间或权限不足不能保证关闭，UI 明确展示保护未确认。

## 开发与验证

运行不需要第三方 Python 包；使用官方 Python 3.14（含 Tk）。在仓库根目录：

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests/windows -v
python -m fourg_bridge.windows.main
```

构建需先批准第三方打包依赖，并核实来源。`requirements-windows-build.lock` 固定 PyPI 官方发布轮子的版本和 SHA-256。使用官方 GitHub Windows runner 预装 NSIS，不从不明下载站安装。

```powershell
python -m pip install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements-windows-build.lock
python script/build_windows.py
```

Windows 工作流 push 默认只运行标准库测试和只读 smoke；人工允许打包后以 workflow_dispatch 的 `package=true` 构建。工作流默认只读仓库权限，上传测试记录、安装包和 SHA-256，发行时单独上传验证后的资产。

验收必须区分：纯逻辑测试、Windows 无设备启动与接口读取、真实 QDC507 的串口／网络／SIM／短信、Wi-Fi 与 VPN 切换、UAC 拒绝、热插拔、睡眠唤醒、80%／98% 边界。没有设备的云端 runner 不能完成最后这些硬件验收。

## 官方接口依据

- [Python Tk/ttk](https://docs.python.org/3/library/tkinter.ttk.html)
- [Windows GetIfEntry2](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-getifentry2)
- [Windows 接口 metric](https://learn.microsoft.com/en-us/windows-server/networking/technologies/network-subsystem/net-sub-interface-metric)
- [TCP EStats](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getpertcpconnectionestats)
- [PyInstaller 官方文档与跨平台限制](https://pyinstaller.org/en/stable/)
- [NSIS 许可证](https://nsis.sourceforge.io/License)
