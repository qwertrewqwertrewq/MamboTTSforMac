-- ==============================================================================
-- MamboTTS for DaVinci Resolve (Lua 原生引导器)
-- 作用：解决 macOS 下 DaVinci Resolve 因缺少系统级 Python.framework 而在菜单中
--       显示 "No scripts" 的问题。通过 Lua 原生引导，100% 确保菜单项稳定出现并
--       调用项目独立的 Apple Silicon 预编译 Python 运行时。
-- ==============================================================================

local home = os.getenv("HOME") or ""
local root_file = home .. "/.mambotts_root"
local project_root = ""

-- 1. 尝试从 ~/.mambotts_root 获取项目路径
local f = io.open(root_file, "r")
if f then
    project_root = f:read("*l") or ""
    f:close()
    project_root = project_root:gsub("%s+", "")
end

-- 2. 若未记录，尝试常用候选目录
if project_root == "" or not io.open(project_root .. "/run_engine.py", "r") then
    local candidates = {
        home .. "/Coding/manbo",
        home .. "/Downloads/MamboTTSforMac",
        home .. "/MamboTTSforMac",
        home .. "/Documents/MamboTTS",
        home .. "/MamboTTS"
    }
    for _, cand in ipairs(candidates) do
        local test_f = io.open(cand .. "/run_engine.py", "r")
        if test_f then
            test_f:close()
            project_root = cand
            break
        end
    end
end

-- 3. 寻找可用的 Python 独立解释器
local python_bin = project_root .. "/GPT-SoVITS/runtime/bin/python"
local f_py = io.open(python_bin, "r")
if f_py then
    f_py:close()
else
    python_bin = project_root .. "/.venv/bin/python"
    f_py = io.open(python_bin, "r")
    if f_py then
        f_py:close()
    else
        python_bin = "python3"
    end
end

-- 4. 执行 Python 配音脚本
local script_py = project_root .. "/davinci-plugin/MamboTTS_Resolve.py"
local cmd = string.format('export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"; export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"; export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"; "%s" "%s" &', python_bin, script_py)

os.execute(cmd)
