#!/usr/bin/env bash
set -e

# 确保在脚本所在目录运行
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 检查 Python 环境（优先使用内置便携运行时）
if [ -f "GPT-SoVITS/runtime/bin/python" ]; then
    PYTHON_CMD="GPT-SoVITS/runtime/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    echo "[错误] 未检测到 Python 3，请先安装 Python 3.10+"
    exit 1
fi

# 启动引导/客户端
"$PYTHON_CMD" bootstrap.py "$@"
