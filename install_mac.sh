#!/usr/bin/env bash
# ==============================================================================
# MamboTTS for Mac 一键安装与部署脚本
# 自动从 Cloudflare R2 高速下载预编译独立运行时与模型整合包
# ==============================================================================
set -e

RED="\033[1;31m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
BOLD="\033[1m"
RESET="\033[0m"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo -e "${CYAN}====================================================${RESET}"
echo -e "${CYAN}${BOLD}         MamboTTS for macOS 一键安装程序            ${RESET}"
echo -e "${CYAN}====================================================${RESET}"

R2_BASE_URL="https://r2.rinku.dpdns.org"
EXPECTED_SHA256="2aa53ec6d12e0c54447f3ab6dd8cbdc86c373a417fc7c9745e386d7be0101623"
TOTAL_PARTS=24

# 1. 检查是否已经存在预编译环境
if [ -f "GPT-SoVITS/runtime/bin/python" ] && [ -f "models/manbo-e10.ckpt" ]; then
    echo -e "${GREEN}[成功] 检测到 GPT-SoVITS 独立运行时和模型已就绪，跳过下载。${RESET}"
else
    if [ ! -f "GPT-SoVITS-v2pro-mac-arm64.tar.gz" ]; then
        echo -e "${GREEN}[1/3] 正在从 Cloudflare R2 下载完整整合包 (约 5.9 GB)...${RESET}"
        echo -e "${YELLOW}下载源: ${R2_BASE_URL}${RESET}"

        # 循环下载 24 个分卷
        for i in $(seq -f "%02g" 0 $((TOTAL_PARTS - 1))); do
            PART_FILE="GPT-SoVITS-v2pro-mac-arm64.tar.gz.part$i"
            PART_URL="${R2_BASE_URL}/${PART_FILE}"
            
            if [ ! -f "$PART_FILE" ]; then
                echo -e "${CYAN}正在下载分卷 [$(expr $i + 1)/$TOTAL_PARTS]: ${PART_FILE}...${RESET}"
                curl -f -L -C - --retry 3 --retry-delay 2 -o "$PART_FILE" "$PART_URL"
            else
                echo -e "${GREEN}[完成] 分卷已存在: ${PART_FILE}${RESET}"
            fi
        done

        echo -e "${GREEN}[2/3] 合并分卷...${RESET}"
        cat GPT-SoVITS-v2pro-mac-arm64.tar.gz.part* > GPT-SoVITS-v2pro-mac-arm64.tar.gz
        rm -f GPT-SoVITS-v2pro-mac-arm64.tar.gz.part*
    else
        echo -e "${GREEN}[提示] 检测到已存在完整整合包，跳过下载分卷。${RESET}"
    fi

    echo -e "正在校验整合包 SHA256 完整性..."
    ACTUAL_SHA256=$(shasum -a 256 GPT-SoVITS-v2pro-mac-arm64.tar.gz | awk '{print $1}')
    if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
        echo -e "${RED}[错误] 文件校验失败！可能下载损坏，请重新运行本脚本。${RESET}"
        echo -e "期望值: $EXPECTED_SHA256"
        echo -e "实际值: $ACTUAL_SHA256"
        rm -f GPT-SoVITS-v2pro-mac-arm64.tar.gz
        exit 1
    fi
    echo -e "${GREEN}[成功] SHA256 校验通过！${RESET}"

    echo -e "正在解压模型与运行时环境..."
    tar -xzf GPT-SoVITS-v2pro-mac-arm64.tar.gz

    # 清理临时下载文件节省空间
    rm -f GPT-SoVITS-v2pro-mac-arm64.tar.gz
    echo -e "${GREEN}[成功] 解压与环境就绪完成！${RESET}"
fi

# 2. 配置达芬奇 (DaVinci Resolve) 插件支持
echo -e "${GREEN}[3/3] 配置达芬奇 (DaVinci Resolve) 脚本...${RESET}"
DAVINCI_SCRIPT_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
if [ -d "$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve" ]; then
    mkdir -p "$DAVINCI_SCRIPT_DIR"
    cp -f "$DIR/davinci-plugin/MamboTTS_Resolve.py" "$DAVINCI_SCRIPT_DIR/MamboTTS_Resolve.py"
    echo "{\"project_root\": \"$DIR\"}" > "$DAVINCI_SCRIPT_DIR/MamboTTS_config.json"
    echo "$DIR" > "$HOME/.mambotts_root"
    echo -e "${GREEN}[成功] 已自动安装达芬奇脚本至: ${DAVINCI_SCRIPT_DIR}/MamboTTS_Resolve.py${RESET}"
    echo -e "${YELLOW}  (在达芬奇顶部菜单: 工作区 -> 脚本 -> Utility -> MamboTTS_Resolve 即可直接呼出)${RESET}"
else
    echo -e "${YELLOW}未检测到达芬奇安装目录，若后续安装达芬奇，可直接运行 davinci-plugin/install_davinci_plugin.sh${RESET}"
fi

# 确保安装标记文件存在，避免平台差异导致的重复检测
touch "$DIR/GPT-SoVITS/.mambo_install_ok" 2>/dev/null || true

# 3. 赋予运行权限
chmod +x run.sh MamboTTS.command MamboTTS_DaVinci.command davinci-plugin/install_davinci_plugin.sh 2>/dev/null || true

echo -e "${CYAN}====================================================${RESET}"
echo -e "${GREEN}[完成] 安装部署全部完成！${RESET}"
echo -e "启动方式："
echo -e "  1. 独立客户端: 双击 ${YELLOW}MamboTTS.command${RESET} 或终端运行 ${YELLOW}./run.sh${RESET}"
echo -e "  2. 达芬奇配音: 打开达芬奇工程后，在菜单【工作区 -> 脚本 -> Utility -> MamboTTS_Resolve】"
echo -e "                或双击 ${YELLOW}MamboTTS_DaVinci.command${RESET}"
echo -e "${CYAN}====================================================${RESET}"
