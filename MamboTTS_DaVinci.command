#!/usr/bin/env bash
# ==============================================================================
# MamboTTS 达芬奇 (DaVinci Resolve) 配音助手独立启动器
# 打开达芬奇工程后，双击此文件直接运行，自动识别文字轨并生成音频！
# ==============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"

if [ -f "GPT-SoVITS/runtime/bin/python" ]; then
    PYTHON_BIN="GPT-SoVITS/runtime/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
else
    PYTHON_BIN="python3"
fi

"$PYTHON_BIN" "davinci-plugin/MamboTTS_Resolve.py" "$@"
