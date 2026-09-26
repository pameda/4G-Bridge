# 4G Bridge Windows 0.2.0-preview.1

面向 Windows 11 x64 的首个预览版，**不包含 iMessage、Apple 账号登录或短信转发**。与 macOS 正式版独立发布。

## 下载与安装

- 推荐下载 `4G-Bridge-0.2.0-preview.1-windows-x64-setup.exe`，安装到当前用户目录。
- 便携版请完整解压 ZIP，再运行 `4G Bridge.exe`，不能只复制 EXE。
- 对照 `windows-SHA256SUMS.txt` 校验下载文件；安装包未签名，可能出现 SmartScreen 提示，不要关闭系统安全保护。
- 不捆绑驱动，不修改模块固件。首次默认只读，网络控制需主动以管理员权限重新启动并接受正常 UAC 提示。

## 已实现

中文六页窗口与系统托盘、QDC507 身份与 COM 通道发现、SIM／LTE 状态、Wi-Fi 故障自动接管逻辑、运营商短信流量查询、套餐环形图、80% 确认与 98% 关闭保护、接口流量计量、中文运行日志、登录启动和有限的 IPv4 TCP 应用网络统计。

运营商查询必须单次确认，可能产生短信费用。查询结果过期、SIM 不明或计量失效时保护性关闭；不自动发送收费查询短信。日志不保存短信正文或敏感标识，模块短信不自动删除。

应用网络统计不包括 UDP／QUIC／IPv6，短连接可能漏采，代理流量可能重复。套餐估算并非运营商实时账单，不能承诺绝不超过套餐额度。

## 验证与限制

- 构建提交：`833a28a7fbb794c55653f5e9fd730ac777c50bcd`。
- [Windows 构建与验收记录](https://github.com/pameda/4G-Bridge/actions/runs/36231330207)：41 项 Windows 测试；EXE 和安装器生成；打包及安装后的六页窗口、托盘启动；系统接口与计数读取；安装／卸载检查通过。
- 本机合计 235 项回归测试、Ruff、mypy、敏感信息扫描通过。下载后 SHA-256 与构建输出一致。
- CI 使用 Windows Server 2022 x64，**没有 QDC507**。Windows 11 真机、串口／SIM／短信、实际 4G 上网、Wi-Fi／VPN 切换、热插拔、睡眠唤醒与交互式视觉验收均待执行；不是稳定版或硬件兼容性认证。
- 不影响现有 macOS 正式版。完整说明见仓库 [WINDOWS.md](https://github.com/pameda/4G-Bridge/blob/main/WINDOWS.md) 和 [TESTING.md](https://github.com/pameda/4G-Bridge/blob/main/TESTING.md)。
