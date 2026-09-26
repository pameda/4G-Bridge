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
# Windows 构建补充（2026-09-26）

Windows 运行代码只依赖官方 CPython / Tcl-Tk 标准发行运行时（PSF / Tcl-Tk 许可证）；与 macOS 的 PyObjC / libusb 依赖分离。

打包工具拟使用 PyInstaller 6.22.3（GPL-2.0-or-later WITH Bootloader-exception，允许分发非 GPL 应用；[官方许可](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt)）、官方项目维护的 hooks-contrib，以及其构建依赖 altgraph、pefile、pywin32-ctypes、packaging、setuptools。来源由官方 PyPI 元数据核验；Windows 专用 lock 文件固定 wheel 哈希。构建复制各 distribution 的 LICENSE/COPYING 与 CPython、Tcl-Tk 许可到安装包，不复制第三方产品源码或品牌素材。

安装器采用 GitHub 官方 Windows runner 预装 NSIS，使用 zlib 压缩，不使用 LZMA。NSIS 主体与 zlib 模块为 zlib/libpng 许可；[官方完整许可](https://nsis.sourceforge.io/License)。未对第三方工具作源码修改。不在用户 Mac 安装这些 Windows 打包工具。
