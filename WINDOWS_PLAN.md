# Windows 版开发计划

状态：已列入下一阶段，尚未实现或发布 Windows 安装包。先完成 macOS 当前版本验收，再开始 Windows 移植；不将本文件视为功能已完成的证明。

## 开始条件

- macOS 完成获准的 Wi-Fi 断开 → 4G 实际联网 → Wi-Fi 恢复循环。
- macOS 完成钥匙串授权后的模块 SMS → Messages → 收件端验证。
- 确认可用 Windows 开发／测试环境及 QDC507 实机。当前 Mac 的常用工具检查未发现 dotnet、PowerShell、Parallels、VirtualBox 或 UTM 命令，尚未验证任何 Windows 主机。

## 平台与架构

- 初步目标 Windows 11 x64；ARM64 在驱动及硬件验证后决定，不预先承诺支持。
- 在本仓库管理共享核心与平台适配层，避免复制两套短信解码、去重、队列和流量保护逻辑。
- 先验证现有 Python 核心在 Windows 的可移植性，再确定发布架构。UI 优先评估 WinUI 3／Windows App SDK 原生方案；如采用独立 Python 核心进程，须明确受限本机 IPC、启动管理与崩溃恢复，不开放网络监听。
- 原生系统托盘、浅深色、键盘导航、辅助功能及中文界面；保持 4G Bridge 视觉一致性，遵循 Windows 平台习惯，不复制 macOS 窗口装饰。
- macOS 系统调用、钥匙串、登录项、网络管理和 Messages 分离为平台接口；Windows 实现独立适配，不调用 networksetup 或 AppleScript。

## 功能范围

- QDC507 识别、AT 通信、SIM／运营商／信号／注册状态、热插拔及睡眠恢复。
- 动态发现模块网络接口，Wi-Fi 优先，获准后自动接管；保留 VPN、DNS 及其他网卡配置。
- 运营商查询及严格套餐解析、百分比环形图、80% 确认／98% 停止保护；继续明确估算及计量延迟，不宣称精确计费硬限额。
- 接口流量、中文脱敏日志、登录启动。按进程网络统计须独立验证系统能力和权限，不能把总流量伪装成应用流量。
- SMS PDU、Unicode、多段组装、去重与失败保留；敏感设置采用 Windows 系统凭据存储，正文不写普通日志或 Git。

## iMessage 边界

当前桥接依赖 macOS Messages.app，不能直接迁移到 Windows。Windows 版保留发送适配接口，未配置经过验证的通道时显示不可用并保留模块短信，不能标记发送成功或删除。

不获取 Apple ID 密码或 Token，不调用非公开 iMessage 协议，不伪造消息，不擅自接入第三方云转发。若希望经用户自己的 Mac 转发，需另行确认远程桥接范围、安全设计和测试；这不是当前已承诺的 Windows V1 功能。

## USB 与供应链安全

- 先只读枚举 VID/PID、接口、COM 端口、网卡和已绑定驱动，验证原始及 EC25 personality。
- Windows 内置 MBIM 支持不代表此模块当前 ECM personality 可用，必须检查实机；不默默切换 USB 模式、改 VID/PID、刷固件或替换驱动绑定。
- 优先系统支持的通道；若需要厂商驱动，先核实官方来源、签名及许可证。任何额外驱动或社区组件安装先说明风险并取得确认，不关闭驱动签名保护。
- 不因移植影响已验证的 macOS AT／网络路径；先抽象接口并运行现有回归测试。

## 交付门槛

- [ ] 共享核心平台隔离与 Windows 单元测试。
- [ ] Windows 实机 USB／AT／SIM／SMS 只读验证。
- [ ] 原生托盘与设置界面、系统凭据和登录启动适配。
- [ ] 用户批准的小流量网络切换、Wi-Fi／VPN 共存及 80%／98% 边界验证。
- [ ] 缺设备、超时、拔插、睡眠唤醒、重启去重、异常退出测试。
- [ ] Windows CI 构建和安装／卸载／升级测试，发布安装包与 SHA-256；签名情况如实说明。
- [ ] 源码、文档、测试结果及发行资产同步本 GitHub 仓库；未实现功能明确标注。

## 官方技术参考

- [Microsoft Windows 桌面应用开发](https://learn.microsoft.com/en-us/windows/apps/desktop/)
- [WinUI 3](https://learn.microsoft.com/windows/apps/winui)
- [Windows 内置移动宽带驱动与 MBIM](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/mb-mbim-interaction-overview)
