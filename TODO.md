# TODO

## V1 硬件验收

- [ ] 接入真实 QDC507 后记录只读 `ATI/CPIN/COPS/CEREG/QNWINFO/CSQ` 结果。
- [ ] 验证 `2CA3:4006` 与 `2C7C:0125` 两种 personality 的 endpoint 重新枚举。
- [ ] 验证模块热插拔、睡眠/唤醒和 ECM 接口重编号。
- [ ] 在用户明确确认后验证数据 ON/OFF、Wi-Fi/VPN 共存与退出恢复 OFF。
- [ ] 在用户明确确认目标后发送一次测试 iMessage。
- [ ] 使用专用测试短信验证成功转发后 `AT+CMGD`，并核对无重复。

## 发布

- [ ] 配置 Apple Developer ID 后替换 ad-hoc 签名并完成公证。
- [ ] 完成 GitHub 私有仓库设备登录与首次 push。
- [ ] 用真实 tag `v0.1.0` 验证 GitHub Actions release。

## V2 预留

- [ ] 经用户单独授权后设计 iMessage → QDC507 SMS 出站协议。
- [ ] 不通过 `chat.db` 或 Full Disk Access 实现入站解析。
