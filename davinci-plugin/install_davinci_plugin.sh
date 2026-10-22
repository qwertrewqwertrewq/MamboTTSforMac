#!/usr/bin/env bash
# ==============================================================================
# 安装 MamboTTS 达芬奇 (DaVinci Resolve) 插件脚本
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
TARGET_EDIT_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"

mkdir -p "$TARGET_DIR"

# 清理历史旧版与重复冗余脚本
rm -f "$TARGET_EDIT_DIR/MamboTTS_Resolve.py" \
      "$TARGET_EDIT_DIR/MamboTTS_Voiceover.lua" \
      "$TARGET_DIR/MamboTTS_Voiceover.lua" 2>/dev/null || true

# 统一安装至 Utility 目录
cp -f "$DIR/MamboTTS_Resolve.py" "$TARGET_DIR/MamboTTS_Resolve.py"
chmod +x "$TARGET_DIR/MamboTTS_Resolve.py" "$DIR/MamboTTS_Resolve.py"

echo "=========================================================="
echo "MamboTTS 达芬奇插件安装/更新成功！"
echo "=========================================================="
echo "使用说明："
echo "1. 打开 DaVinci Resolve (达芬奇)"
echo "2. 打开你的剪辑工程并切换到 Edit (剪辑) 页面"
echo "3. 确保时间线上已有【字幕轨 (Subtitle)】或【Text+ 标题轨】"
echo "4. 在达芬奇顶部菜单栏点击："
echo "   工作区 (Workspace) -> 脚本 (Scripts) -> Utility -> MamboTTS_Resolve"
echo "5. 在弹出的窗口中点击「一键生成配音并插入时间线」即可！"
echo "=========================================================="
