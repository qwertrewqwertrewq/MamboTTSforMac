#!/usr/bin/env bash
# ==============================================================================
# MamboTTS macOS 双击启动器
# ==============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. 若未安装预编译环境，自动拉起一键安装脚本
if [ ! -f "GPT-SoVITS/runtime/bin/python" ] && [ ! -f ".venv/bin/python" ]; then
    echo "未检测到预编译独立运行时，正在启动一键安装程序..."
    ./install_mac.sh
fi

# 2. 确定 Python 解释器
if [ -f "GPT-SoVITS/runtime/bin/python" ]; then
    PYTHON_CMD="GPT-SoVITS/runtime/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    osascript -e 'display alert "错误" message "未检测到 Python 3，请先安装 Python 3.10+" as critical'
    exit 1
fi

# 3. 自动同步达芬奇 (DaVinci Resolve) 插件与配置
DAVINCI_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
if [ -d "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve" ]; then
    mkdir -p "$DAVINCI_DIR"
    cp -f "$DIR/davinci-plugin/MamboTTS_Resolve.py" "$DAVINCI_DIR/MamboTTS_Resolve.py" 2>/dev/null || true
    echo "{\"project_root\": \"$DIR\"}" > "$DAVINCI_DIR/MamboTTS_config.json" 2>/dev/null || true
    echo "$DIR" > "$HOME/.mambotts_root" 2>/dev/null || true
fi

# 4. 启动应用主界面
"$PYTHON_CMD" launcher.py "$@"
