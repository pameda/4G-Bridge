# Third-Party Notices

本项目为独立实现。以下 Python 组件来自官方 PyPI，具体版权文本随各发行包提供：

| 组件 | 版本 | 许可证 |
|---|---:|---|
| PyObjC core/Cocoa/Security | 12.2.2 | MIT |
| py2app | 0.28.10 | MIT / Python Software Foundation |
| PyUSB | 1.3.1 | BSD-3-Clause |
| libusb-package | 1.0.30.0 | Apache-2.0；内含 libusb 为 LGPL-2.1-or-later |
| pytest / pytest-cov | 8.4.2 / 7.0.0 | MIT |
| coverage.py | 7.16.1 | Apache-2.0 |
| Ruff | 0.13.2 | MIT |
| mypy | 1.18.2 | MIT |
| setuptools / wheel / packaging | 锁定版本见 lockfile | MIT / Apache-2.0 / BSD |
| altgraph / macholib / modulegraph | 锁定版本见 lockfile | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |

研究参考：

- `HD838A/dji-4g-mac`：未发现 LICENSE，不复制源码。
- `miaopantao/DJI4G-releases-cn`：发行物/说明仓库未发现源码许可，不复制内容。
- `4G-Connect`：MIT，仅核验通用设计思路。
- `qdc507-macos-serial-driver`：Apache-2.0，仅核验 USB 描述符；其需要改变系统安全策略的 DriverKit 路线未采用。
- `EC25Toolbox`：AGPL-3.0，只研究外部行为，不复制源码。

本项目不包含上述参考项目的 Logo、图标、名称、品牌素材或受保护源码。
