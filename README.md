<h1 align="center">MamboTTS for macOS & Windows</h1>

<p align="center"><strong>面向解说与短视频创作场景的本地拟真语音合成工具与达芬奇 (DaVinci Resolve) 剪辑插件</strong></p>

<p align="center">
  <a href="https://rinku.dpdns.org"><strong>[项目官网与架构介绍: rinku.dpdns.org]</strong></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/macOS-Apple_Silicon-0A0A0B?style=flat-square" alt="macOS" />
  <img src="https://img.shields.io/badge/Windows-10%2F11_64位-0A0A0B?style=flat-square" alt="Windows" />
  <img src="https://img.shields.io/badge/GPU-Apple_MPS_%2F_NVIDIA-0A0A0B?style=flat-square" alt="GPU" />
  <img src="https://img.shields.io/badge/Engine-GPT--SoVITS-0A0A0B?style=flat-square" alt="GPT-SoVITS" />
  <img src="https://img.shields.io/badge/Version-v1.2.1_MacPro-0A0A0B?style=flat-square" alt="v1.2.1" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-0A0A0B?style=flat-square" alt="MIT" /></a>
</p>

> 基于 GPT-SoVITS，在本地 GPU（Apple Silicon MPS / NVIDIA CUDA）上毫秒级合成高质量拟真解说语音。不仅提供独立桌面客户端，还深度整合 **达芬奇 (DaVinci Resolve)** 剪辑轨，一键批量转换时间线文字为独立音频轨。

---

## 项目官网与源码下载

- **官方网站 / 原理介绍**：[https://rinku.dpdns.org](https://rinku.dpdns.org)
- **GitHub 源码仓库**：[https://github.com/qwertrewqwertrewq/MamboTTSforMac](https://github.com/qwertrewqwertrewq/MamboTTSforMac)
- **源码包直链 (适合无 Git 用户)**：[https://rinku.dpdns.org/MamboTTSforMac-source.zip](https://rinku.dpdns.org/MamboTTSforMac-source.zip)

---

## macOS 快速开始 (Apple Silicon M 系列)

macOS 版本已全面适配 Apple Silicon (MPS 硬件加速)，内置免配置独立 Python 运行时、GPT-SoVITS 底模及曼波权重，开箱即用。

### 方式 A：源码压缩包安装（推荐，无需安装 Git）
1. 下载源码压缩包：[MamboTTSforMac-source.zip](https://rinku.dpdns.org/MamboTTSforMac-source.zip) 并解压。
2. 打开解压后的文件夹，双击运行 `install_mac.sh`（或在终端运行 `./install_mac.sh`）。
3. 脚本将自动从 Cloudflare R2 极速拉取预编译运行时环境与模型并自动就绪。

### 方式 B：Git 仓库克隆（开发者推荐）
在终端中执行：
```bash
git clone https://github.com/qwertrewqwertrewq/MamboTTSforMac.git
cd MamboTTSforMac
./install_mac.sh
```

### 启动方式
- **独立桌面客户端**：双击运行 `MamboTTS.command` 或在终端运行 `./run.sh`。
- **达芬奇 (DaVinci Resolve) 剪辑插件**：
  1. 打开达芬奇项目并进入剪辑时间线；
  2. 在达芬奇顶部菜单选择：**工作区 (Workspace) -> 脚本 (Scripts) -> Utility -> MamboTTS_Resolve**；
  3. 或者直接双击运行项目根目录下的 `MamboTTS_DaVinci.command`。
  4. 插件将自动识别当前时间线上的所有字幕轨或 Text+ 标题字幕，一键调用 GPT-SoVITS 批量生成音频，并精准按字幕起止时间直接追加在对应时间线音频轨上，支持自动轨道裁剪与对齐！

---

## Windows 快速开始

### 1. 下载并解压

前往 [Releases](https://github.com/Tsukimisaka/MamboTTS/releases) 下载 `MamboTTS-v1.2.1-full.zip`，解压到全英文路径，例如 `D:\MamboTTS\`。

| 内容 | 说明 |
| --- | --- |
| 客户端 | 发布包内含桌面图形客户端与预设音色 |
| 引擎本体 | 发布包不含，首次运行时自动下载（约 8.2GB） |

### 2. 双击启动

双击 `MamboTTS.bat`。

- 首次运行自动安装依赖并下载引擎：多源自动测速选最快，支持断点续传与失败自动换源，界面实时显示下载百分比 / 速度 / 剩余量。
- 引擎就绪后进入主界面（首次约 10–30 秒），关闭窗口时引擎自动退出。

### 3. 输入并合成

在文本框输入解说文案 → 调节语速 → 点击「合成配音」。完成后可在播放器试听，历史记录支持回放与另存。

## 系统要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 / 11 64 位 |
| 显卡 | NVIDIA GPU（50 系与其余 NVIDIA 对应不同整合包，安装时按 nvidia-smi 自动预选） |
| 网络 | 首次运行需联网下载引擎约 8.2GB；合成阶段可离线 |
| 磁盘 | 需容纳下载包及解压后的引擎与模型，建议预留 30GB+ |
| 解压路径 | 须为全英文路径，中文路径可能导致引擎加载异常 |

## 常见问题

<details>
<summary>安装很慢或看起来卡住？</summary>

安装器内置多源下载（ModelScope / hf-mirror / HuggingFace 等自动测速选最快），下载期间实时显示百分比、速度与剩余量；单源失败自动切换，中断后重新双击可断点续传。
</details>

<details>
<summary>所有下载源都失败怎么办？</summary>

两种自救方式：在 `mirrors.txt` 中添加可用镜像；或手动下载整合包放入 `engine_temp/` 后重试安装（安装器会跳过下载直接解压）。详见「高级配置」。
</details>

<details>
<summary>一直显示引擎启动中？</summary>

首次加载约需 10–30 秒属正常。若超时，界面提供「重启引擎」入口，并可在运行日志中查看具体原因。
</details>

## 工作原理

MamboTTS 是 GPT-SoVITS 的 Windows 图形客户端与启动器。本仓库**不包含、也不修改** GPT-SoVITS 本体：引擎整合包在首次运行时从云端下载，客户端通过本地 HTTP API（`127.0.0.1:9880`）调用，接口契约见 `engine_contract.py`。

## 编辑器扩展

仓库 `Premiere-Pro-UXP/` 目录提供用于 Premiere Pro 的 UXP 配音插件，由 [@2710165659](https://github.com/2710165659) 贡献，为独立于主客户端的编辑器扩展，适用于在 Premiere Pro 内发起配音与试听。

| 文件 / 目录 | 说明 |
| --- | --- |
| `index.html` / 相关 JS | 插件面板与逻辑 |
| `styles.css` | 面板样式 |
| `manifest.json` | UXP 插件清单 |
| `install.ps1` | Windows 安装脚本 |
| `preview-player/` | 基于 Rust 的预览播放器 |

Premiere Pro 为 Adobe 商标，本项目与其不存在隶属或背书关系。

## 高级配置

- **自定义下载镜像**：编辑 `mirrors.txt`，每行一个 URL 模板（`{file}` 为整合包文件名占位符）。
- **手动放置整合包**：将 7z 文件放入 `engine_temp/` 后重新运行安装，即可跳过下载。
- **自建 / 远程引擎**：主界面「引擎接口」可填写自定义服务地址（对应 `config.json` 的 `api_url`）。
- **配置文件**：`config.json` 由程序自动生成，模板见 `config.example.json`。

## 开发者

| 模块 | 职责 |
| --- | --- |
| `app.py` | 主界面：合成 / 播放器 / 历史 / 日志 / 主题 |
| `launcher.py` · `bootstrap.py` | 启动引导与一键安装 |
| `install_engine.py` | 引擎多源下载与解压 |
| `inference.py` | 引擎 HTTP 客户端 |
| `theme.py` | 深浅双主题样式 |

## 免责声明

本软件仅供个人学习、技术研究与学术交流使用。用户需自行确保参考音频与生成内容的权利合规，并承担相应使用责任；严禁将生成的声音用于诈骗、仿冒、侵犯他人声音权 / 肖像权等非法用途。

## 致谢与许可

引擎基于 [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)。

感谢 [@2710165659](https://github.com/2710165659) 贡献的 Premiere Pro UXP 插件支持。

本项目基于 [MIT](LICENSE) 许可开源；GPT-SoVITS 引擎本体遵循其上游许可。
