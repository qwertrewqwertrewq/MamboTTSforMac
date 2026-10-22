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

# 各分卷预设大小 (字节)
PART_SIZES=(
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    262144000
    259678971
)

# 各分卷 SHA256 校验和
PART_SHAS=(
    "5e8ef0ffb821c59085245a27b83d5354e3b0459d7206fc394337bbda8f91b516"
    "0cce154e93e83c709f458cbcff847a9a2be0d13eee87d7cb258d0428bfb09665"
    "75a7191afd84e1b59f0a6925084dbfe906dda785d78f10e5b4493904c4a6ca15"
    "dfb962f0b53a7a2b5ad2de272a235fd90daf7840033453f15b7ab59690633682"
    "c644ca4ee2d1818ac768fb8c9a33743440c46f381146abe47c2655d9fd526bc8"
    "c55ab581e40dcdbcf3508eb15a56e534735cf22b548b12a9fb9efaf7609b4432"
    "e158b01f2fd62325f99a4ce99db0ba8d4c91d5f8b0135e0cb72aef26d5491cc8"
    "bfbb6a3df8b6ba40039353e6c075c639a01cf98adb0fd753e2caaac27a368310"
    "97bf04473138d00e244a6efbd2473750f7551e14b1b0b091a6cf0badd16f857b"
    "e64470b14be2dbbb4e8f90e4b93f2f117eae4be7da55c0868589e085ad167336"
    "fae4b22edd47cf569b32283c7a754a17feaa67080949945b205056239956c83e"
    "fc4212e6750701b3da1eda94676e216fedbdb58465b2869a61aebc5f6a705d98"
    "8e1b9fceaa1465258815c84f3895e9fe6257072474f6cbe0ab711962fd177b4c"
    "2e5b5066eb3a1553d05051d17d241964b69c5395d281563bbb55a3e0cdfa8d41"
    "2b00a68ffd2907d678024c31be85f4ba47b36da506c82f7ddd6cd4c2b0f3cd37"
    "cace3ace6ec0ae538518b8720c38e8a3cfcd211f3b696702fb7a6f02805aeb52"
    "2f4f7a4e164ff9e32bae3fa26f56d088582779895ac2824a3115b49f29ff29a2"
    "dbd090f0e5f129569609889754b40ef12c3965ba53fe8dbd5617afd832c8e59e"
    "2b0c5039d0286d027696ae948432d9f450de47c57c9fa2c619a381ad6b4afb3b"
    "efdf87ef5e7a99504f3903dd684c073c5195e990de031b6f16e12357db449529"
    "13cbdf72f292cdca453f97649e2e83ffa125426c1b2e90d9df58ad33e4e2287d"
    "17420816065f25b03d4798a1aa7f43578ed1cfdaceed6afdbca7a1107e2310a9"
    "cc26cad842927946f94625809e5f5d5c04e5973fb21a38c2be2c8df42dc7f715"
    "b2437f96b49c554dd48d471f5b8beade31f228deb6e7969bf83a9afac0b8a00d"
)

# 单分卷精准校验函数 (优先比对大小，一致再比对 SHA256)
verify_part() {
    local file="$1"
    local exp_size="$2"
    local exp_sha="$3"

    if [ ! -f "$file" ]; then
        return 1
    fi

    # 1. 快速检查文件大小
    local act_size
    act_size=$(stat -f %z "$file" 2>/dev/null || wc -c < "$file" | tr -d ' ')
    if [ "$act_size" -ne "$exp_size" ]; then
        return 1
    fi

    # 2. 精准比对 SHA256
    local act_sha
    act_sha=$(shasum -a 256 "$file" | awk '{print $1}')
    if [ "$act_sha" = "$exp_sha" ]; then
        return 0
    else
        return 1
    fi
}

# 1. 检查是否已经存在预编译环境
if [ -f "GPT-SoVITS/runtime/bin/python" ] && [ -f "models/manbo-e10.ckpt" ]; then
    echo -e "${GREEN}[成功] 检测到 GPT-SoVITS 独立运行时和模型已就绪，跳过下载。${RESET}"
else
    if [ ! -f "GPT-SoVITS-v2pro-mac-arm64.tar.gz" ]; then
        echo -e "${GREEN}[1/3] 正在从 Cloudflare R2 下载完整整合包 (约 5.9 GB)...${RESET}"
        echo -e "${YELLOW}下载源: ${R2_BASE_URL}${RESET}"

        # 循环下载并逐一校验 24 个分卷
        for i in $(seq 0 $((TOTAL_PARTS - 1))); do
            INDEX_STR=$(printf "%02d" $i)
            PART_FILE="GPT-SoVITS-v2pro-mac-arm64.tar.gz.part${INDEX_STR}"
            PART_URL="${R2_BASE_URL}/${PART_FILE}"
            EXP_SIZE="${PART_SIZES[$i]}"
            EXP_SHA="${PART_SHAS[$i]}"
            HUMAN_INDEX=$((i + 1))

            # 本地已存在该文件时进行完整性检验，避免中断残片被误判为已完成
            if [ -f "$PART_FILE" ]; then
                echo -n -e "检测已有分卷 [${HUMAN_INDEX}/${TOTAL_PARTS}]: ${PART_FILE}，正在校验..."
                if verify_part "$PART_FILE" "$EXP_SIZE" "$EXP_SHA"; then
                    echo -e " ${GREEN}[通过]${RESET}"
                    continue
                else
                    echo -e " ${YELLOW}[未完成或损坏]${RESET}"
                    echo -e "${YELLOW}[提示] 分卷未完成或校验不匹配，准备断点续传/重新下载...${RESET}"
                fi
            fi

            # 下载与校验重试机制 (最多尝试 3 轮)
            PART_OK=0
            for attempt in 1 2 3; do
                echo -e "${CYAN}正在下载分卷 [${HUMAN_INDEX}/${TOTAL_PARTS}] (尝试 ${attempt}/3): ${PART_FILE}...${RESET}"
                # 先尝试断点续传 (-C -)
                if ! curl -f -L -C - --retry 3 --retry-delay 2 --connect-timeout 15 -o "$PART_FILE" "$PART_URL"; then
                    echo -e "${YELLOW}[警告] 断点续传失败，清除残存片段重新下载...${RESET}"
                    rm -f "$PART_FILE"
                    curl -f -L --retry 3 --retry-delay 2 --connect-timeout 15 -o "$PART_FILE" "$PART_URL" || true
                fi

                echo -n -e "正在校验分卷 [${HUMAN_INDEX}/${TOTAL_PARTS}] 完整性..."
                if verify_part "$PART_FILE" "$EXP_SIZE" "$EXP_SHA"; then
                    echo -e " ${GREEN}[校验通过]${RESET}"
                    PART_OK=1
                    break
                else
                    echo -e " ${RED}[校验失败]${RESET}"
                    echo -e "${YELLOW}[警告] 分卷校验未通过，移除残缺文件准备重试...${RESET}"
                    rm -f "$PART_FILE"
                    sleep 1
                fi
            done

            if [ "$PART_OK" -ne 1 ]; then
                echo -e "${RED}[错误] 分卷 ${PART_FILE} 多次下载校验均失败，请检查网络后重新运行本脚本。${RESET}"
                exit 1
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
