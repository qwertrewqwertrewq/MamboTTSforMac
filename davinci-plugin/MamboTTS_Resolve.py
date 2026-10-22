#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MamboTTS 配音助手 for DaVinci Resolve (达芬奇)
可视化交互窗口版 (基于 DaVinci Resolve 原生 UIManager / Qt 框架)

功能：
  1. 可视化界面：直观查看当前时间线、引擎状态、扫描到的台词列表及实时进度日志
  2. 音频尾部空白优化：自动检测并截除生成的音频尾部多余空白静音（保留自然衰减），大幅提升紧凑度
  3. 轨道裁剪与对齐：支持可勾选自动裁剪文字轨道以精确匹配音频时长，支持左对齐/右对齐切换
  4. 重叠音频处理：默认同轨覆盖写入；可勾选遇到时间重叠时自动新建音频轨道放置
  5. 自动检测与一键启动：引擎离线时提供一键唤起后台本地引擎功能
"""

import os
import sys
import time
import json
import wave
import struct
import tempfile
import traceback
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

# ==============================================================================
# 系统弹窗与日志工具 (保证在任何情况下都能让用户直观看到报错与状态)
# ==============================================================================

LOG_FILE = os.path.expanduser("~/Library/Logs/MamboTTS_Resolve.log")

def write_log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def show_native_alert(title, message, is_error=True):
    """弹出 macOS 原生对话框 (异步执行，不阻塞 UI 调度器)"""
    icon = "stop" if is_error else "note"
    clean_msg = message.replace('"', '\\"').replace("'", "’")
    clean_title = title.replace('"', '\\"').replace("'", "’")
    script = f'''display dialog "{clean_msg}" with title "{clean_title}" buttons {{"好的"}} default button "好的" with icon {icon}'''
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"弹窗失败: {e}")


# ==============================================================================
# 连接 DaVinci Resolve 脚本环境
# ==============================================================================

def get_resolve():
    """获取 DaVinci Resolve 实例 (兼容菜单内直接调用与外部启动)"""
    # 1. 尝试全局变量注入 (菜单点击时达芬奇会自动注入 resolve)
    try:
        if "resolve" in globals() and globals()["resolve"] is not None:
            return globals()["resolve"]
    except Exception:
        pass

    # 2. 尝试从官方模块导入
    module_paths = [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
        os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
    ]
    for p in module_paths:
        if os.path.exists(p) and p not in sys.path:
            sys.path.append(p)

    try:
        import DaVinciResolveScript as dvr_script
        return dvr_script.scriptapp("Resolve")
    except Exception as e:
        write_log(f"加载 DaVinciResolveScript 失败: {e}")
        return None


# ==============================================================================
# MamboTTS 引擎通信与音频处理
# ==============================================================================

DEFAULT_API_URL = "http://127.0.0.1:9880"

def is_engine_online(api_url=DEFAULT_API_URL):
    """检测本地或远程 TTS 引擎是否在线"""
    for endpoint in ("/control", "/"):
        try:
            req = urllib.request.Request(api_url.rstrip("/") + endpoint, method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as response:
                if response.status in (200, 400, 405):
                    return True
        except Exception:
            continue
    return False


def get_project_root():
    """获取 MamboTTS 项目根目录"""
    # 1. 尝试直接从当前脚本所在目录向上查找 (适用于从工程目录直接运行)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cand_root = os.path.dirname(script_dir)
    if os.path.exists(os.path.join(cand_root, "run_engine.py")):
        return cand_root

    # 2. 尝试从同级配置文件 MamboTTS_config.json 读取
    config_file = os.path.join(script_dir, "MamboTTS_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                root = cfg.get("project_root", "")
                if root and os.path.exists(os.path.join(root, "run_engine.py")):
                    return root
        except Exception:
            pass

    # 3. 尝试从用户全局配置 ~/.mambotts_root 读取
    root_file = os.path.expanduser("~/.mambotts_root")
    if os.path.exists(root_file):
        try:
            with open(root_file, "r", encoding="utf-8") as f:
                root = f.read().strip()
                if root and os.path.exists(os.path.join(root, "run_engine.py")):
                    return root
        except Exception:
            pass

    # 4. 常见候选路径兜底
    for cand in [
        os.path.expanduser("~/Coding/manboo"),
        os.path.expanduser("~/MamboTTS"),
        os.path.expanduser("~/Documents/MamboTTS"),
        os.path.expanduser("~/Downloads/MamboTTSforMac"),
        os.path.expanduser("~/MamboTTSforMac"),
    ]:
        if os.path.exists(os.path.join(cand, "run_engine.py")):
            return cand

    return cand_root


def start_local_engine():
    """在后台拉起本地 MamboTTS 主客户端与推理引擎"""
    project_root = get_project_root()
    engine_py = os.path.join(project_root, "GPT-SoVITS", "runtime", "bin", "python")
    if not os.path.exists(engine_py):
        engine_py = sys.executable

    launcher_script = os.path.join(project_root, "launcher.py")
    run_engine_script = os.path.join(project_root, "run_engine.py")

    target_script = launcher_script if os.path.exists(launcher_script) else run_engine_script
    if not os.path.exists(target_script):
        return False, "未找到启动脚本，请先手动运行主客户端 MamboTTS.command"

    try:
        subprocess.Popen(
            [engine_py, target_script],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "正在唤醒主客户端与引擎..."
    except Exception as e:
        return False, str(e)


def synthesize_speech(text, output_path, speed=1.2, api_url=DEFAULT_API_URL):
    """请求 TTS 引擎生成 wav"""
    url = api_url.rstrip("/") + "/"
    payload = {
        "text": text,
        "text_language": "zh",
        "speed": float(speed),
        "cut_punc": "，。？！；：、…,.;?!",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
            with open(output_path, "wb") as f:
                f.write(response.read())
        return True, "合成成功"
    except Exception as e:
        return False, str(e)


def trim_wav_trailing_silence(wav_path, buffer_ms=60):
    """
    检测并去除 WAV 音频尾部的空白无声部分。
    保留 buffer_ms (默认 60ms) 的平滑衰减，并在最后 15ms 应用防破音淡出。
    返回 (原始时长秒, 裁剪后时长秒)。
    """
    try:
        with wave.open(wav_path, "rb") as wf:
            params = wf.getparams()
            nchannels, sampwidth, framerate, nframes = params[:4]
            raw_bytes = wf.readframes(nframes)

        if sampwidth != 2 or nframes == 0:
            dur = nframes / float(framerate) if framerate > 0 else 0.0
            return dur, dur

        fmt = f"<{nframes * nchannels}h"
        samples = list(struct.unpack(fmt, raw_bytes))

        # 计算峰值振幅
        max_val = max(abs(s) for s in samples) if samples else 0
        if max_val == 0:
            return 0.0, 0.0

        # 阈值：峰值的 1.5% 或最小 300
        threshold = max(int(max_val * 0.015), 300)

        # 从末尾倒序扫描，找到最后一个有声音的采样点
        last_voiced_frame = nframes - 1
        for f in range(nframes - 1, -1, -1):
            base_idx = f * nchannels
            if any(abs(samples[base_idx + ch]) > threshold for ch in range(nchannels)):
                last_voiced_frame = f
                break

        buffer_frames = int(framerate * (buffer_ms / 1000.0))
        keep_frames = min(nframes, last_voiced_frame + 1 + buffer_frames)

        if keep_frames < nframes:
            trimmed_samples = samples[:keep_frames * nchannels]

            # 末尾 15ms 进行线性平滑淡出，彻底避免切音爆音
            fade_frames = min(int(framerate * 0.015), keep_frames)
            for f in range(fade_frames):
                factor = (fade_frames - 1 - f) / float(fade_frames)
                frame_idx = keep_frames - fade_frames + f
                for ch in range(nchannels):
                    idx = frame_idx * nchannels + ch
                    trimmed_samples[idx] = int(trimmed_samples[idx] * factor)

            out_bytes = struct.pack(f"<{len(trimmed_samples)}h", *trimmed_samples)
            with wave.open(wav_path, "wb") as wf:
                wf.setparams((
                    nchannels, sampwidth, framerate,
                    len(trimmed_samples) // nchannels,
                    params[4], params[5]
                ))
                wf.writeframes(out_bytes)

            old_dur = nframes / float(framerate)
            new_dur = (len(trimmed_samples) // nchannels) / float(framerate)
            return old_dur, new_dur

        dur = nframes / float(framerate)
        return dur, dur
    except Exception as e:
        write_log(f"音频尾部去空白失败: {e}")
        try:
            with wave.open(wav_path, "rb") as wf:
                dur = wf.getnframes() / float(wf.getframerate())
                return dur, dur
        except Exception:
            return 0.0, 0.0


def get_audio_duration_seconds(file_path):
    try:
        with wave.open(file_path, "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        return 0.0


# ==============================================================================
# 时间线文本提取与重叠判定逻辑
# ==============================================================================

def extract_timeline_texts(timeline):
    """提取时间线上的所有字幕轨与 Text+ 片段，附带剪辑对象引用"""
    items_data = []

    # 1. 字幕轨 (Subtitle Tracks)
    subtitle_track_count = timeline.GetTrackCount("subtitle") or 0
    for track_idx in range(1, subtitle_track_count + 1):
        track_name = timeline.GetTrackName("subtitle", track_idx) or f"Subtitle {track_idx}"
        clips = timeline.GetItemListInTrack("subtitle", track_idx) or []
        for clip in clips:
            name = clip.GetName() or ""
            start = clip.GetStart()
            end = clip.GetEnd()
            dur = clip.GetDuration()
            text = name.strip()
            if text:
                items_data.append({
                    "track_type": "subtitle",
                    "track_index": track_idx,
                    "track_name": track_name,
                    "text": text,
                    "start_frame": start,
                    "end_frame": end,
                    "duration_frames": dur,
                    "clip_obj": clip,
                })

    # 2. 视频轨上的 Text+ (Fusion 标题)
    video_track_count = timeline.GetTrackCount("video") or 0
    for track_idx in range(1, video_track_count + 1):
        track_name = timeline.GetTrackName("video", track_idx) or f"Video {track_idx}"
        clips = timeline.GetItemListInTrack("video", track_idx) or []
        for clip in clips:
            name = clip.GetName() or ""
            start = clip.GetStart()
            end = clip.GetEnd()
            dur = clip.GetDuration()
            text_found = ""

            # 探测 Fusion Comp 中的 StyledText
            comp_count = clip.GetFusionCompCount() or 0
            if comp_count > 0:
                comp = clip.GetFusionCompByIndex(1)
                if comp:
                    tools = comp.GetToolList() or {}
                    for tool_name, tool_obj in tools.items():
                        styled_text = tool_obj.GetInput("StyledText")
                        if styled_text is not None and str(styled_text).strip():
                            text_found = str(styled_text).strip()
                            break

            # 若未从 Fusion 找到，检查 clip 名字是否是文字内容
            if not text_found:
                if name and not any(name.lower().endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".png", ".jpg", ".jpeg", ".wav", ".mp3", ".aac")):
                    if name not in ("Text+", "Title", "字幕", "标题", "Adjustment Clip"):
                        text_found = name.strip()

            if text_found:
                items_data.append({
                    "track_type": "video_textplus",
                    "track_index": track_idx,
                    "track_name": track_name,
                    "text": text_found,
                    "start_frame": start,
                    "end_frame": end,
                    "duration_frames": dur,
                    "clip_obj": clip,
                })

    items_data.sort(key=lambda x: x["start_frame"])
    return items_data


def check_intervals_overlap(s1, e1, s2, e2):
    """判断两个帧区间是否存在重叠"""
    return max(s1, s2) < min(e1, e2)


# ==============================================================================
# 可视化窗口 (基于 DaVinci Resolve 原生 UIManager / Qt)
# ==============================================================================

def run_gui():
    write_log("启动 MamboTTS DaVinci 插件...")

    resolve = get_resolve()
    if not resolve:
        err = "未能连接到正在运行的 DaVinci Resolve！\n请确保达芬奇已启动且偏好设置中允许外部脚本连接。"
        write_log(err)
        show_native_alert("MamboTTS 启动失败", err, is_error=True)
        return

    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        err = "当前未打开任何达芬奇工程！\n请先在达芬奇中双击打开一个工程项目后再运行此脚本。"
        write_log(err)
        show_native_alert("提示", err, is_error=True)
        return

    timeline = project.GetCurrentTimeline()
    if not timeline:
        err = f"工程【{project.GetName()}】未打开任何时间线！\n请先在剪辑 (Edit) 页面打开一条时间线后再运行此脚本。"
        write_log(err)
        show_native_alert("提示", err, is_error=True)
        return

    # 获取 Fusion 实例与 UI 管理器
    try:
        import DaVinciResolveScript as dvr
    except Exception:
        dvr = None

    fu = globals().get("fu") or globals().get("fusion")
    if not fu:
        try:
            fu = resolve.Fusion()
        except Exception:
            fu = None

    if not fu:
        err = "无法获取 Fusion 实例，请检查 DaVinci Resolve 版本是否支持 Fusion 脚本。"
        write_log(err)
        show_native_alert("错误", err, is_error=True)
        return

    ui = fu.UIManager
    bmd_obj = globals().get("bmd")
    if bmd_obj and hasattr(bmd_obj, "UIDispatcher"):
        dispatcher = bmd_obj.UIDispatcher(ui)
    elif dvr and hasattr(dvr, "UIDispatcher"):
        dispatcher = dvr.UIDispatcher(ui)
    elif hasattr(fu, "UIDispatcher"):
        dispatcher = fu.UIDispatcher(ui)
    else:
        err = "无法获取 UIDispatcher 界面调度器！"
        write_log(err)
        show_native_alert("错误", err, is_error=True)
        return

    # 关键防护：修复 Blackmagic Python UIDispatcher 在旧窗口残留事件时的 KeyError('On') 崩溃
    _orig_dispatch = dispatcher.__class__.Dispatch

    def _safe_dispatch(self, ev):
        if not ev:
            return
        win_id = ev.get("window")
        if win_id and (win_id not in self._data or not hasattr(self._data[win_id], "On")):
            return
        try:
            return _orig_dispatch(self, ev)
        except (KeyError, TypeError):
            return

    dispatcher.__class__.Dispatch = _safe_dispatch

    winID = "com.mambotts.resolve_assistant"

    # 若已有实例打开，直接唤醒
    existing_win = ui.FindWindow(winID)
    if existing_win:
        existing_win.Show()
        existing_win.Raise()
        return

    fps = float(timeline.GetSetting("timelineFrameRate") or 25.0)
    timeline_name = timeline.GetName()

    # 布局定义
    win = dispatcher.AddWindow({
        "ID": winID,
        "WindowTitle": f"MamboTTS 曼波自动配音助手 - [{timeline_name}]",
        "Geometry": [220, 120, 840, 640],
    }, ui.VGroup([
        # 1. 顶部状态栏
        ui.HGroup({"Weight": 0}, [
            ui.Label({
                "ID": "TimelineTitle",
                "Text": f"<b>时间线：</b>{timeline_name} ({fps:.2f} fps)",
                "Weight": 1
            }),
            ui.Label({
                "ID": "EngineStatusLabel",
                "Text": "[状态] 正在检测引擎...",
                "Weight": 0
            }),
            ui.HGap(8),
            ui.Button({
                "ID": "StartEngineBtn",
                "Text": "启动引擎",
                "Weight": 0,
                "Visible": False
            }),
        ]),
        ui.Label({"Text": "<hr>", "Weight": 0}),

        # 2. 控制参数行 1：基础参数
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "配音语速:", "Weight": 0}),
            ui.ComboBox({"ID": "SpeedCombo", "Weight": 0.35}),
            ui.HGap(12),
            ui.Label({"Text": "目标音频轨:", "Weight": 0}),
            ui.ComboBox({"ID": "AudioTrackCombo", "Weight": 0.65}),
            ui.HGap(12),
            ui.Button({"ID": "RefreshBtn", "Text": "重新扫描文字轨", "Weight": 0.4}),
        ]),

        # 3. 控制参数行 2：对齐与重叠设置 (新增功能)
        ui.HGroup({"Weight": 0}, [
            ui.CheckBox({
                "ID": "AutoTrimCheck",
                "Text": "自动裁剪文字轨道与音频对齐",
                "Checked": True,
                "Weight": 0
            }),
            ui.HGap(10),
            ui.Label({"ID": "AlignLabel", "Text": "对齐方式:", "Weight": 0}),
            ui.ComboBox({"ID": "AlignCombo", "Weight": 0.25}),
            ui.HGap(15),
            ui.CheckBox({
                "ID": "OverlapTrackCheck",
                "Text": "遇到重叠时新建轨道放置 (默认覆盖)",
                "Checked": False,
                "Weight": 0
            }),
        ]),

        # 4. 提取的台词表格
        ui.Label({"Text": "<b>时间线扫描到的台词片段预览：</b>", "Weight": 0}),
        ui.Tree({"ID": "ClipTree", "Weight": 1.2}),

        # 5. 实时日志预览窗口
        ui.Label({"Text": "<b>操作日志与运行状态：</b>", "Weight": 0}),
        ui.TextEdit({
            "ID": "LogBox",
            "Weight": 0.8,
            "ReadOnly": True,
            "Font": ui.Font({"Family": "Menlo", "PixelSize": 11})
        }),

        # 6. 底部按钮与状态
        ui.HGroup({"Weight": 0}, [
            ui.Label({"ID": "StatusText", "Text": "就绪", "Weight": 1}),
            ui.Button({
                "ID": "GenerateBtn",
                "Text": "一键生成配音并插入时间线",
                "Weight": 0
            }),
            ui.HGap(8),
            ui.Button({"ID": "CloseBtn", "Text": "关闭", "Weight": 0}),
        ]),
    ]))

    # UI 控件引用
    engine_label = win.Find("EngineStatusLabel")
    start_engine_btn = win.Find("StartEngineBtn")
    speed_combo = win.Find("SpeedCombo")
    track_combo = win.Find("AudioTrackCombo")
    auto_trim_check = win.Find("AutoTrimCheck")
    align_combo = win.Find("AlignCombo")
    overlap_track_check = win.Find("OverlapTrackCheck")
    clip_tree = win.Find("ClipTree")
    log_box = win.Find("LogBox")
    status_label = win.Find("StatusText")
    generate_btn = win.Find("GenerateBtn")

    # 日志输出函数
    def log(msg):
        write_log(msg)
        ts = datetime.now().strftime("%H:%M:%S")
        current = log_box.PlainText or ""
        log_box.PlainText = f"{current}[{ts}] {msg}\n"

    log(f"成功连接 DaVinci Resolve！工程: {project.GetName()}, 时间线: {timeline_name}")

    # 填充语速
    speeds = [
        ("0.8x (较慢)", 0.8),
        ("1.0x (原速)", 1.0),
        ("1.1x (微快)", 1.1),
        ("1.2x (推荐曼波解说)", 1.2),
        ("1.3x (快语速)", 1.3),
        ("1.5x (极速)", 1.5),
    ]
    for label, _ in speeds:
        speed_combo.AddItem(label)
    speed_combo.CurrentIndex = 3  # 默认 1.2x

    # 填充对齐选项
    align_combo.AddItem("左对齐 (默认)")
    align_combo.AddItem("右对齐")
    align_combo.CurrentIndex = 0

    # 填充音频轨选项
    def refresh_tracks():
        track_combo.Clear()
        track_combo.AddItem("+ 自动新建 Mono 音频轨 (MamboTTS 配音)")
        cnt = timeline.GetTrackCount("audio") or 0
        for i in range(1, cnt + 1):
            tname = timeline.GetTrackName("audio", i) or f"Audio {i}"
            track_combo.AddItem(f"A{i}: {tname}")
        track_combo.CurrentIndex = 0

    refresh_tracks()

    # 初始化表格
    clip_tree.ColumnCount = 4
    clip_tree.SetHeaderLabels(["序号", "来源轨道", "时间码范围 (帧)", "台词文字内容"])

    scanned_items = []

    def refresh_scanned_items():
        nonlocal scanned_items
        clip_tree.Clear()
        log("正在扫描时间线字幕轨与 Text+ 文字片段...")
        scanned_items = extract_timeline_texts(timeline)
        if not scanned_items:
            log("[警告] 未在当前时间线上检测到任何字幕或 Text+ 片段！")
            status_label.Text = "<font color='#EF4444'>未检测到任何文字片段，请确保时间线上有 Text+ 或字幕轨</font>"
            return

        for idx, item in enumerate(scanned_items, 1):
            row = clip_tree.NewItem()
            row.Text[0] = str(idx)
            row.Text[1] = f"{item['track_name']} ({item['track_type']})"
            row.Text[2] = f"{item['start_frame']} ~ {item['end_frame']} ({item['duration_frames']}帧)"
            row.Text[3] = item["text"]
            clip_tree.AddTopLevelItem(row)

        msg = f"扫描完毕：共找到 {len(scanned_items)} 条文字片段。"
        log(f"[成功] {msg}")
        status_label.Text = f"已就绪：共检测到 {len(scanned_items)} 条文字片段"

    def update_engine_status():
        online = is_engine_online()
        if online:
            engine_label.Text = "<font color='#10B981'><b>[在线] MamboTTS 引擎已连接 (127.0.0.1:9880)</b></font>"
            start_engine_btn.Visible = False
            generate_btn.Enabled = True
        else:
            engine_label.Text = "<font color='#EF4444'><b>[离线] MamboTTS 引擎未启动</b></font>"
            start_engine_btn.Visible = True
            generate_btn.Enabled = False
            log("提示：MamboTTS 引擎离线，请点击「启动引擎」或运行主客户端 MamboTTS.command")

            # 若主客户端完全未运行，自动在后台尝试唤醒一次
            try:
                proc_out = subprocess.check_output(["pgrep", "-f", "launcher\\.py|app\\.py"]).decode().strip()
            except Exception:
                proc_out = ""
            if not proc_out:
                log("[提示] 检测到 MamboTTS 主客户端尚未启动，正在后台自动唤醒...")
                start_local_engine()
                engine_label.Text = "<font color='#F59E0B'><b>[启动中] 正在唤醒主客户端与引擎...</b></font>"

    # 绑定事件
    def on_auto_trim_toggled(ev):
        align_combo.Enabled = bool(auto_trim_check.Checked)

    def on_start_engine(ev):
        log("正在拉起本地 MamboTTS 推理后端...")
        ok, msg = start_local_engine()
        if not ok:
            log(f"[错误] 启动失败: {msg}")
            show_native_alert("启动失败", msg, is_error=True)
            return

        engine_label.Text = "<font color='#F59E0B'><b>[启动中] 引擎正在初始化，约需 5~10 秒...</b></font>"
        log("引擎进程已启动，正在等待端口 9880 监听就绪...")
        # 轮询 15 秒
        for _ in range(15):
            time.sleep(1.0)
            if is_engine_online():
                log("[就绪] MamboTTS 引擎已成功连接！")
                update_engine_status()
                return
        log("[警告] 等待引擎就绪超时，请检查终端日志或手动运行 ./run.sh")
        update_engine_status()

    def on_refresh(ev):
        refresh_tracks()
        refresh_scanned_items()
        update_engine_status()

    def on_generate(ev):
        if not is_engine_online():
            show_native_alert("提示", "MamboTTS 引擎尚未运行！请先启动引擎。", is_error=True)
            return
        if not scanned_items:
            show_native_alert("提示", "当前没有检测到任何台词文本，无法配音！", is_error=True)
            return

        speed_val = speeds[speed_combo.CurrentIndex][1]
        sel_track_idx = track_combo.CurrentIndex
        do_auto_trim = bool(auto_trim_check.Checked)
        align_mode = "left" if align_combo.CurrentIndex == 0 else "right"
        allow_new_track_on_overlap = bool(overlap_track_check.Checked)

        # 确定基准目标音频轨
        if sel_track_idx == 0:
            timeline.AddTrack("audio", "mono")
            base_target_track = timeline.GetTrackCount("audio")
            timeline.SetTrackName("audio", base_target_track, "MamboTTS 配音")
            log(f"已新建基准音频轨: A{base_target_track} (MamboTTS 配音)")
        else:
            base_target_track = sel_track_idx
            log(f"指定基准音频轨: A{base_target_track}")

        cache_dir = os.path.join(tempfile.gettempdir(), "MamboTTS_Resolve")
        os.makedirs(cache_dir, exist_ok=True)

        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder()

        # 媒体池素材箱
        mambo_folder = None
        for f in root_folder.GetSubFolderList() or []:
            if f.GetName() == "Mambo TTS":
                mambo_folder = f
                break
        if not mambo_folder:
            mambo_folder = media_pool.AddSubFolder(root_folder, "Mambo TTS")

        media_pool.SetCurrentFolder(mambo_folder)

        total = len(scanned_items)
        success_count = 0
        align_text = "左对齐" if align_mode == "left" else "右对齐"
        trim_desc = f"自动裁剪文字轨 ({align_text})" if do_auto_trim else "保持文字原长"
        overlap_desc = "新建分轨放置" if allow_new_track_on_overlap else "默认同轨覆盖"

        log(f"开始批量处理共 {total} 个片段 | 语速: {speed_val}x | {trim_desc} | 重叠处理: {overlap_desc}")

        # 记录已分配轨道的占用区间: {track_index: [(start_frame, end_frame), ...]}
        allocated_intervals = {base_target_track: []}

        for i, item in enumerate(scanned_items, 1):
            short_text = item['text'][:20] + ("..." if len(item['text']) > 20 else "")
            status_label.Text = f"正在处理 [{i}/{total}]: {short_text}"
            log(f"[{i}/{total}] 调用 GPT-SoVITS 合成: 「{short_text}」")

            wav_name = f"mambo_{item['start_frame']}_{i}.wav"
            wav_path = os.path.join(cache_dir, wav_name)

            ok, err_msg = synthesize_speech(item["text"], wav_path, speed=speed_val)
            if not ok:
                log(f"[失败] [{i}/{total}] 合成失败: {err_msg}")
                continue

            # 1. 自动检测并去除尾部空白过长
            old_dur, new_dur = trim_wav_trailing_silence(wav_path, buffer_ms=60)
            if old_dur - new_dur > 0.05:
                log(f"[优化] [{i}/{total}] 尾部空白已裁剪: {old_dur:.3f}s -> {new_dur:.3f}s (截除 {old_dur - new_dur:.3f}s 无效静音)")

            dur_frames = max(1, int(new_dur * fps))

            # 2. 计算对齐位置
            text_start = item["start_frame"]
            text_end = item["end_frame"]
            text_dur = item["duration_frames"]

            if do_auto_trim:
                if align_mode == "left":
                    record_frame = text_start
                    # 裁剪文字轨：如果是 Text+，设置 Fusion Comp 有效结束范围
                    if item["track_type"] == "video_textplus" and item.get("clip_obj"):
                        try:
                            comp = item["clip_obj"].GetFusionCompByIndex(1)
                            if comp:
                                target_render_end = float(min(text_dur - 1, dur_frames - 1))
                                comp.SetAttrs({
                                    "COMPN_RenderEnd": target_render_end,
                                    "COMPN_GlobalEnd": target_render_end,
                                })
                        except Exception as e:
                            write_log(f"调整 Text+ 范围出错: {e}")
                    log(f"[对齐] 左对齐：音频与文字已同步在帧 {record_frame} ~ {record_frame + dur_frames}")
                else:
                    # 右对齐
                    record_frame = max(text_start, text_end - dur_frames)
                    if item["track_type"] == "video_textplus" and item.get("clip_obj"):
                        try:
                            comp = item["clip_obj"].GetFusionCompByIndex(1)
                            if comp:
                                target_render_start = float(max(0, text_dur - dur_frames))
                                comp.SetAttrs({
                                    "COMPN_RenderStart": target_render_start,
                                    "COMPN_GlobalStart": target_render_start,
                                })
                        except Exception as e:
                            write_log(f"调整 Text+ 范围出错: {e}")
                    log(f"[对齐] 右对齐：音频与文字已同步在帧 {record_frame} ~ {text_end}")
            else:
                record_frame = text_start

            audio_end_frame = record_frame + dur_frames

            # 3. 重叠检测与轨道分配
            if not allow_new_track_on_overlap:
                # 默认行为：同轨覆盖
                assigned_track = base_target_track
            else:
                # 勾选了遇到重叠时新建轨道：查找无重叠轨道，或新建轨道
                assigned_track = None
                for t_idx in sorted(allocated_intervals.keys()):
                    overlap_found = any(
                        check_intervals_overlap(record_frame, audio_end_frame, s, e)
                        for s, e in allocated_intervals[t_idx]
                    )
                    if not overlap_found:
                        assigned_track = t_idx
                        break

                if assigned_track is None:
                    # 当前所有轨道均存在重叠冲突，新建一条 Mono 轨道
                    timeline.AddTrack("audio", "mono")
                    assigned_track = timeline.GetTrackCount("audio")
                    sub_idx = len(allocated_intervals) + 1
                    timeline.SetTrackName("audio", assigned_track, f"MamboTTS 配音 {sub_idx}")
                    allocated_intervals[assigned_track] = []
                    log(f"[重叠处理] 检测到音频冲突，已新建轨道 A{assigned_track} 放置重叠片段")

                allocated_intervals[assigned_track].append((record_frame, audio_end_frame))

            # 4. 导入 Media Pool 并插入时间线
            clips = media_pool.ImportMedia([wav_path])
            if not clips:
                log(f"[警告] [{i}/{total}] 音频导入媒体池失败: {wav_path}")
                continue

            clip = clips[0]

            res = media_pool.AppendToTimeline([{
                "mediaPoolItem": clip,
                "startFrame": 0,
                "endFrame": dur_frames,
                "recordFrame": record_frame,
                "trackIndex": assigned_track,
                "mediaType": 2,  # 2: Audio Only
            }])
            if res:
                log(f"[成功] [{i}/{total}] 音频已插入 A{assigned_track} 轨 (起始帧: {record_frame}, 时长: {dur_frames}帧)")
                success_count += 1
            else:
                log(f"[警告] [{i}/{total}] 插入时间线返回空，请检查轨道是否被锁定")

        result_msg = f"批量配音完成！成功生成并插入 {success_count}/{total} 个片段。"
        log(result_msg)
        status_label.Text = f"<font color='#10B981'><b>{result_msg}</b></font>"
        show_native_alert("配音完成", f"全部配音生成完毕！\n共成功生成并插入 {success_count}/{total} 个音频片段到时间线。", is_error=False)

    def on_close(ev):
        dispatcher.ExitLoop()

    # 注册事件
    win.On[winID].Close = on_close
    win.On["CloseBtn"].Clicked = on_close
    win.On["RefreshBtn"].Clicked = on_refresh
    win.On["StartEngineBtn"].Clicked = on_start_engine
    win.On["GenerateBtn"].Clicked = on_generate
    win.On["AutoTrimCheck"].Clicked = on_auto_trim_toggled

    # 首次自动检测与扫描
    update_engine_status()
    refresh_scanned_items()

    # 弹出窗口
    win.Show()
    dispatcher.RunLoop()


if __name__ == "__main__":
    try:
        run_gui()
    except Exception as e:
        tb = traceback.format_exc()
        write_log(f"未捕获严重异常: {tb}")
        show_native_alert("MamboTTS 脚本运行错误", f"脚本运行出错：{e}\n\n详细错误见日志文件：\n{LOG_FILE}", is_error=True)
