#!/usr/bin/env bash
# ==============================================================================
# MamboTTS 达芬奇 (DaVinci Resolve) 配音助手独立启动器
# 打开达芬奇工程后，双击此文件直接运行，自动识别文字轨并生成音频！
# ==============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. 自动同步达芬奇插件脚本与配置
DAVINCI_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
if [ -d "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve" ]; then
    mkdir -p "$DAVINCI_DIR"
    cp -f "davinci-plugin/MamboTTS_Resolve.lua" "$DAVINCI_DIR/MamboTTS_Resolve.lua" 2>/dev/null || true
    rm -f "$DAVINCI_DIR/MamboTTS_Resolve.py" 2>/dev/null || true
    echo "{\"project_root\": \"$DIR\"}" > "$DAVINCI_DIR/MamboTTS_config.json" 2>/dev/null || true
    echo "$DIR" > "$HOME/.mambotts_root" 2>/dev/null || true
fi

# 2. 确定 Python 解释器
if [ -f "GPT-SoVITS/runtime/bin/python" ]; then
    PYTHON_BIN="GPT-SoVITS/runtime/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
else
    PYTHON_BIN="python3"
fi

# 3. 同步唤醒 MamboTTS 主客户端（带 GUI 界面与推理引擎）
if ! pgrep -f "launcher\.py|app\.py" >/dev/null 2>&1; then
    echo "[提示] 正在同步唤醒 MamboTTS 主客户端与语音引擎..."
    nohup "$PYTHON_BIN" launcher.py >/dev/null 2>&1 &
    sleep 1
fi

# 4. 设置达芬奇脚本环境变量并启动配音助手窗口
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"

"$PYTHON_BIN" "davinci-plugin/MamboTTS_Resolve.py" "$@"
