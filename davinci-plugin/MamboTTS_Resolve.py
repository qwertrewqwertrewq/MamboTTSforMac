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
import re
import time
import json
import wave
import struct
import tempfile
import traceback
import subprocess
import urllib.request
import urllib.parse
from html.parser import HTMLParser
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


def frames_to_timecode(frame_num, fps, drop_frame=False):
    """根据帧数与帧率计算标准 SMPTE 时间码字符串"""
    fps_int = int(round(fps))
    if not drop_frame:
        ff = int(frame_num % fps_int)
        total_seconds = int(frame_num // fps_int)
        ss = int(total_seconds % 60)
        total_minutes = int(total_seconds // 60)
        mm = int(total_minutes % 60)
        hh = int(total_minutes // 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
    else:
        drop_frames = 2 if fps_int == 30 else (4 if fps_int == 60 else 0)
        if drop_frames == 0:
            return frames_to_timecode(frame_num, fps, False)
        frames_per_minute = fps_int * 60 - drop_frames
        frames_per_10minutes = fps_int * 600 - drop_frames * 9
        d = int(frame_num // frames_per_10minutes)
        m = int(frame_num % frames_per_10minutes)
        if m > drop_frames:
            frame_num += drop_frames * 9 * d + drop_frames * ((m - drop_frames) // frames_per_minute)
        else:
            frame_num += drop_frames * 9 * d
        ff = int(frame_num % fps_int)
        total_seconds = int(frame_num // fps_int)
        ss = int(total_seconds % 60)
        total_minutes = int(total_seconds // 60)
        mm = int(total_minutes % 60)
        hh = int(total_minutes // 60)
        return f"{hh:02d}:{mm:02d}:{ss:02d};{ff:02d}"


def trim_timeline_clip(timeline, track_type, track_index, clip_start, clip_end, cut_frame, fps, is_tail=True, log_fn=None):
    """
    通过在目标分割帧触发快捷键分割与非波纹删除，实现时间线文字片段（Text+ 或字幕轨）的物理缩减裁剪。
    自动保护/锁定所有非目标轨道，防止其他轨道素材被误切。
    """
    if log_fn is None:
        log_fn = print

    if cut_frame <= clip_start or cut_frame >= clip_end:
        log_fn(f"[提示] 裁剪点 {cut_frame} 超出片段有效区间 [{clip_start}, {clip_end}]，无需裁剪缩减")
        return True

    drop_frame = str(timeline.GetSetting("timelineDropFrameTimecode") or "").strip().lower() in ("1", "true")

    # 1. 记录所有轨道锁定状态，并临时锁定其他所有轨道
    locked_states = {}
    for tt in ["video", "audio", "subtitle"]:
        count = timeline.GetTrackCount(tt) or 0
        for t_idx in range(1, count + 1):
            is_locked = timeline.GetIsTrackLocked(tt, t_idx)
            locked_states[(tt, t_idx)] = is_locked
            if (tt, t_idx) != (track_type, track_index) and not is_locked:
                timeline.SetTrackLock(tt, t_idx, True)
            if (tt, t_idx) == (track_type, track_index) and is_locked:
                timeline.SetTrackLock(tt, t_idx, False)

    try:
        # 2. 定位播放头至分割帧
        tc = frames_to_timecode(cut_frame, fps, drop_frame=drop_frame)
        timeline.SetCurrentTimecode(tc)
        time.sleep(0.06)

        # 3. 触发 Cmd+B 切割
        cmd = '''osascript -e 'tell application "DaVinci Resolve" to activate' -e 'tell application "System Events" to keystroke "b" using {command down}' '''
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            err = proc.stderr.strip()
            log_fn(f"[提示] 自动裁剪快捷键未执行: {err} (如需自动物理裁切，请在「系统偏好设置 -> 隐私与安全性 -> 辅助功能」中允许控制)")
            return False

        time.sleep(0.08)

        # 4. 找到并删除被分割出来的多余片段
        clips = timeline.GetItemListInTrack(track_type, track_index) or []
        target_to_delete = None
        for c in clips:
            c_start = c.GetStart()
            c_end = c.GetEnd()
            if is_tail:
                # 裁切尾部：寻找分割出来的后半段
                if abs(c_start - cut_frame) <= 2 and abs(c_end - clip_end) <= 2:
                    target_to_delete = c
                    break
            else:
                # 裁切头部：寻找分割出来的前半段
                if abs(c_start - clip_start) <= 2 and abs(c_end - cut_frame) <= 2:
                    target_to_delete = c
                    break

        if target_to_delete:
            del_ok = timeline.DeleteClips([target_to_delete], False)
            if del_ok:
                log_fn(f"[对齐] 成功裁切轨道 {track_type}{track_index} 文字片段，移除多余区间 [{target_to_delete.GetStart()} ~ {target_to_delete.GetEnd()}]")
            return del_ok
        else:
            log_fn(f"[警告] 未在轨道 {track_type}{track_index} 找到待删除的分割片段 (cut_frame={cut_frame}, is_tail={is_tail})")
            return False
    except Exception as e:
        log_fn(f"[错误] 执行时间线裁切出错: {e}")
        return False
    finally:
        # 5. 恢复所有轨道原始锁定状态
        for (tt, t_idx), orig_locked in locked_states.items():
            timeline.SetTrackLock(tt, t_idx, orig_locked)


def extend_timeline_clip(timeline, track_type, track_index, clip_start, clip_end, target_end, fps, log_fn=None):
    """
    通过移动播放头至目标延长位置并触发 Extend Edit (快捷键 'e')，
    实现时间线文字片段（Text+ 或字幕轨）向右延长与音频对齐。
    自动保护/锁定所有非目标轨道。
    """
    if log_fn is None:
        log_fn = print

    if target_end <= clip_end:
        return True

    # 1. 检测同轨道后方紧邻片段，避免超出可用间隙引起冲突
    clips = timeline.GetItemListInTrack(track_type, track_index) or []
    next_clip_start = None
    for c in clips:
        cs = c.GetStart()
        if cs >= clip_end:
            if next_clip_start is None or cs < next_clip_start:
                next_clip_start = cs

    if next_clip_start is not None and target_end > next_clip_start:
        target_end = next_clip_start
        log_fn(f"[提示] 目标延长位置超出后方片段间隙，受限延长至后方片段起点 (帧 {next_clip_start})")

    if target_end <= clip_end:
        log_fn(f"[提示] 轨道 {track_type}{track_index} 后方无空隙，无法继续延长")
        return False

    drop_frame = str(timeline.GetSetting("timelineDropFrameTimecode") or "").strip().lower() in ("1", "true")

    # 2. 记录所有轨道锁定状态，并临时锁定其他所有轨道
    locked_states = {}
    for tt in ["video", "audio", "subtitle"]:
        count = timeline.GetTrackCount(tt) or 0
        for t_idx in range(1, count + 1):
            is_locked = timeline.GetIsTrackLocked(tt, t_idx)
            locked_states[(tt, t_idx)] = is_locked
            if (tt, t_idx) != (track_type, track_index) and not is_locked:
                timeline.SetTrackLock(tt, t_idx, True)
            if (tt, t_idx) == (track_type, track_index) and is_locked:
                timeline.SetTrackLock(tt, t_idx, False)

    try:
        # 3. 播放头定位到片段出点并按 'v' 选中编辑点
        tc_end = frames_to_timecode(clip_end, fps, drop_frame=drop_frame)
        timeline.SetCurrentTimecode(tc_end)
        time.sleep(0.06)

        cmd_v = '''osascript -e 'tell application "DaVinci Resolve" to activate' -e 'tell application "System Events" to keystroke "v"' '''
        proc_v = subprocess.run(cmd_v, shell=True, capture_output=True, text=True)
        if proc_v.returncode != 0:
            log_fn(f"[提示] 延长快捷键未执行: {proc_v.stderr.strip()}")
            return False

        time.sleep(0.06)

        # 4. 播放头移动到目标延长帧并按 'e' 触发 Extend Edit
        tc_target = frames_to_timecode(target_end, fps, drop_frame=drop_frame)
        timeline.SetCurrentTimecode(tc_target)
        time.sleep(0.06)

        cmd_e = '''osascript -e 'tell application "DaVinci Resolve" to activate' -e 'tell application "System Events" to keystroke "e"' '''
        proc_e = subprocess.run(cmd_e, shell=True, capture_output=True, text=True)
        if proc_e.returncode != 0:
            log_fn(f"[提示] Extend Edit 快捷键未执行: {proc_e.stderr.strip()}")
            return False

        time.sleep(0.08)

        # 5. 验证是否延长成功
        clips_after = timeline.GetItemListInTrack(track_type, track_index) or []
        for c in clips_after:
            if abs(c.GetStart() - clip_start) <= 2:
                new_dur = c.GetDuration()
                new_end = c.GetEnd()
                log_fn(f"[对齐] 成功将轨道 {track_type}{track_index} 文字片段延长至帧 {new_end} (时长增加至 {new_dur}帧)")
                return True

        return True
    except Exception as e:
        log_fn(f"[错误] 延长文字片段过程异常: {e}")
        return False
    finally:
        # 6. 还原所有轨道锁定状态
        for (tt, t_idx), orig_locked in locked_states.items():
            timeline.SetTrackLock(tt, t_idx, orig_locked)


def split_text_into_chunks(text, max_chars=8):
    """
    智能按最大字数切分台词：
    优先按标点符号自然断句；若单句仍超过 max_chars，则按字数均匀切片。
    """
    if not text or len(text) <= max_chars:
        return [text] if text else []

    parts = re.split(r'([，,。!！?？；;\s]+)', text)
    chunks = []
    curr = ""
    for part in parts:
        if not part:
            continue
        if len(curr) + len(part) <= max_chars:
            curr += part
        else:
            if curr.strip():
                chunks.append(curr.strip())
            curr = part

    if curr.strip():
        chunks.append(curr.strip())

    final_chunks = []
    for c in chunks:
        if len(c) <= max_chars:
            final_chunks.append(c)
        else:
            n = (len(c) + max_chars - 1) // max_chars
            step = len(c) / n
            for i in range(n):
                sub = c[int(round(i * step)): int(round((i + 1) * step))].strip()
                if sub:
                    final_chunks.append(sub)

    return final_chunks or [text]


def split_timeline_clip_by_length(timeline, track_type, track_index, clip_start, clip_end, text, max_chars, fps, log_fn=None):
    """
    在文字片段已完成音频对齐后，按指定字数智能拆分时间线文字轨道（先对齐后拆分编辑）。
    自动锁定保护非目标轨道，并在拆分后尝试同步更新 Text+ 子片段台词。
    """
    if log_fn is None:
        log_fn = print

    if not text or len(text) <= max_chars:
        return True

    chunks = split_text_into_chunks(text, max_chars)
    if len(chunks) <= 1:
        return True

    total_chars = sum(len(c) for c in chunks)
    total_dur = clip_end - clip_start
    if total_dur < len(chunks) * 3:
        log_fn(f"[提示] 片段时长过短 ({total_dur}帧)，跳过按字数拆分")
        return False

    drop_frame = str(timeline.GetSetting("timelineDropFrameTimecode") or "").strip().lower() in ("1", "true")

    # 1. 记录所有轨道锁定状态，并临时锁定其他所有轨道
    locked_states = {}
    for tt in ["video", "audio", "subtitle"]:
        count = timeline.GetTrackCount(tt) or 0
        for t_idx in range(1, count + 1):
            is_locked = timeline.GetIsTrackLocked(tt, t_idx)
            locked_states[(tt, t_idx)] = is_locked
            if (tt, t_idx) != (track_type, track_index) and not is_locked:
                timeline.SetTrackLock(tt, t_idx, True)
            if (tt, t_idx) == (track_type, track_index) and is_locked:
                timeline.SetTrackLock(tt, t_idx, False)

    try:
        # 2. 计算各个分割点的目标帧
        accum_chars = 0
        cut_frames = []
        for i in range(len(chunks) - 1):
            accum_chars += len(chunks[i])
            c_frame = clip_start + round(total_dur * (accum_chars / total_chars))
            if clip_start + 2 < c_frame < clip_end - 2:
                if not cut_frames or c_frame > cut_frames[-1] + 2:
                    cut_frames.append(c_frame)

        if not cut_frames:
            return True

        # 3. 逐点切割
        for cut_f in cut_frames:
            tc = frames_to_timecode(cut_f, fps, drop_frame=drop_frame)
            timeline.SetCurrentTimecode(tc)
            time.sleep(0.06)
            cmd = '''osascript -e 'tell application "DaVinci Resolve" to activate' -e 'tell application "System Events" to keystroke "b" using {command down}' '''
            subprocess.run(cmd, shell=True, capture_output=True, text=True)
            time.sleep(0.06)

        log_fn(f"[拆分] 成功按每段约 {max_chars} 字将轨道 {track_type}{track_index} 文字拆分为 {len(cut_frames) + 1} 个子片段")

        # 4. 若为 Text+，更新拆分后各个子片段的 StyledText 内容
        time.sleep(0.08)
        sub_clips = [c for c in (timeline.GetItemListInTrack(track_type, track_index) or [])
                     if c.GetStart() >= clip_start - 2 and c.GetEnd() <= clip_end + 2]
        sub_clips.sort(key=lambda x: x.GetStart())

        if len(sub_clips) == len(chunks):
            for idx, sc in enumerate(sub_clips):
                if sc.GetFusionCompCount() > 0:
                    try:
                        comp = sc.GetFusionCompByIndex(1)
                        if comp:
                            tools = comp.GetToolList() or {}
                            for t_name, t_obj in tools.items():
                                if hasattr(t_obj, "GetInput") and t_obj.GetInput("StyledText") is not None:
                                    t_obj.SetInput("StyledText", chunks[idx])
                                    break
                    except Exception as e:
                        write_log(f"更新 Text+ 子片段文字失败: {e}")

        return True
    except Exception as e:
        log_fn(f"[错误] 自动拆分文字轨道异常: {e}")
        return False
    finally:
        # 恢复所有轨道锁定状态
        for (tt, t_idx), orig_locked in locked_states.items():
            timeline.SetTrackLock(tt, t_idx, orig_locked)


# ==============================================================================
# 时间线文本提取与常规标题解析逻辑
# ==============================================================================

class CleanHTMLTextExtractor(HTMLParser):
    """提取 HTML 标签中的可读文本，忽略 style, script, head 等样式与元数据"""
    def __init__(self):
        super().__init__()
        self.texts = []
        self.ignore = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("style", "script", "head"):
            self.ignore = True

    def handle_endtag(self, tag):
        if tag.lower() in ("style", "script", "head"):
            self.ignore = False

    def handle_data(self, data):
        if not self.ignore:
            t = data.strip()
            if t:
                self.texts.append(t)

    def get_text(self):
        return " ".join(self.texts)


def extract_text_from_html(html_str):
    """解析富文本 HTML 字符串为纯文本台词"""
    if not html_str:
        return ""
    p = CleanHTMLTextExtractor()
    try:
        p.feed(html_str)
        return p.get_text().strip()
    except Exception:
        return ""


def is_template_or_media_name(name):
    """检测片段名称是否属于内置模板、生成器或音视频媒体文件名（避免误将模板名作为台词朗读）"""
    if not name:
        return True
    lower = name.lower().strip()
    media_exts = (
        ".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm",
        ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".psd",
        ".wav", ".mp3", ".aac", ".m4a", ".flac", ".aif", ".aiff"
    )
    if any(lower.endswith(ext) for ext in media_exts):
        return True

    patterns = [
        r"字幕条", r"标题", r"title", r"lower third", r"scroll", r"滚动",
        r"text\+?", r"文本", r"富文本", r"rich text", r"rich lower",
        r"adjustment", r"调整片段", r"fusion", r"generator", r"生成器",
        r"solid color", r"单色"
    ]
    for pat in patterns:
        if re.search(pat, lower):
            return True
    return False


def get_otio_title_map(timeline, resolve):
    """
    通过导出临时 OTIO 文件解析达芬奇常规标题（非 Fusion/Text+，如中下方字幕条、文本等）的富文本参数。
    Resolve 原生导出 OTIO 耗时通常在 30ms 左右，解析后立即自动删除临时文件。
    返回映射: {(track_index, rel_start_frame): combined_text}
    """
    title_map = {}
    if not timeline or not resolve:
        return title_map
    if not hasattr(resolve, "EXPORT_OTIO"):
        return title_map

    tmp_path = os.path.join(tempfile.gettempdir(), f"mambotts_temp_{os.getpid()}_{int(time.time()*1000)}.otio")
    try:
        export_ok = timeline.Export(tmp_path, resolve.EXPORT_OTIO)
        if export_ok and os.path.exists(tmp_path):
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.loads(f.read())

            video_tracks = [t for t in data.get("tracks", {}).get("children", []) if t.get("kind") == "Video"]
            for v_idx, vt in enumerate(video_tracks):
                track_num = v_idx + 1
                curr_frame = 0.0
                for child in vt.get("children", []):
                    schema = child.get("OTIO_SCHEMA", "")
                    sr = child.get("source_range", {})
                    dur = sr.get("duration", {}).get("value", 0.0)
                    start_frame = round(curr_frame)
                    curr_frame += dur

                    if schema.startswith("Gap"):
                        continue

                    texts = []
                    media_refs = child.get("media_references", {})
                    for ref_k, ref_v in media_refs.items():
                        if not isinstance(ref_v, dict):
                            continue
                        params = ref_v.get("parameters", {}).get("Resolve_OTIO", [])
                        for p_group in params:
                            for p in p_group.get("Parameters", []):
                                for k, v in p.items():
                                    if "Title HTML" in k and isinstance(v, str):
                                        txt = extract_text_from_html(v)
                                        if txt:
                                            texts.append(txt)

                    combined_text = " ".join(texts).strip()
                    if combined_text:
                        title_map[(track_num, start_frame)] = combined_text
    except Exception as e:
        write_log(f"OTIO 解析标题异常: {e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return title_map


def extract_timeline_texts(timeline, resolve=None):
    """提取时间线上的所有字幕轨与 Text+ / 常规标题片段，附带剪辑对象引用"""
    if not resolve:
        resolve = get_resolve()

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
            if text and not is_template_or_media_name(text):
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

    # 2. 视频轨上的 Text+ 与常规标题模板
    tl_start = timeline.GetStartFrame() or 0
    otio_title_map = get_otio_title_map(timeline, resolve)

    video_track_count = timeline.GetTrackCount("video") or 0
    for track_idx in range(1, video_track_count + 1):
        track_name = timeline.GetTrackName("video", track_idx) or f"Video {track_idx}"
        clips = timeline.GetItemListInTrack("video", track_idx) or []
        for clip in clips:
            name = clip.GetName() or ""
            start = clip.GetStart()
            end = clip.GetEnd()
            dur = clip.GetDuration()
            rel_start = start - tl_start
            text_found = ""

            # 探测 Fusion Comp 中的 StyledText (Text+)
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

            # 若未从 Fusion 找到，尝试从 OTIO 导出的参数中匹配 Title HTML (中下方字幕条、文本等常规标题)
            if not text_found and otio_title_map:
                for delta in (0, -1, 1, -2, 2):
                    key = (track_idx, rel_start + delta)
                    if key in otio_title_map:
                        text_found = otio_title_map[key]
                        break

            # 若仍未找到，仅当 clip 名称不是模板、生成器或媒体文件名时，才作为备用台词
            if not text_found:
                if not is_template_or_media_name(name):
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
        "WindowTitle": f"MamboTTS 曼波自动配音助手 v0.1.1 - [{timeline_name}]",
        "Geometry": [180, 80, 940, 720],
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

        # 3. 控制参数行 2：对齐与重叠设置
        ui.HGroup({"Weight": 0}, [
            ui.CheckBox({
                "ID": "AutoTrimCheck",
                "Text": "自动裁剪/延长文字轨道与音频对齐",
                "Checked": True,
                "Weight": 0
            }),
            ui.HGap(10),
            ui.Label({"ID": "AlignLabel", "Text": "对齐方式:", "Weight": 0}),
            ui.ComboBox({"ID": "AlignCombo", "Weight": 0.25}),
            ui.HGap(15),
            ui.CheckBox({
                "ID": "OverlapTrackCheck",
                "Text": "遇到重叠时新建音频轨放置",
                "Checked": False,
                "Weight": 0
            }),
        ]),

        # 4. 控制参数行 3：按字数自动拆分字幕轨道 (先对齐后拆分编辑)
        ui.HGroup({"Weight": 0}, [
            ui.CheckBox({
                "ID": "AutoSplitCheck",
                "Text": "按指定字数自动拆分字幕轨道 (先对齐后拆分编辑)",
                "Checked": False,
                "Weight": 0
            }),
            ui.HGap(8),
            ui.Label({"Text": "单段字数上限:", "Weight": 0}),
            ui.SpinBox({
                "ID": "SplitCharSpin",
                "Value": 8,
                "Minimum": 3,
                "Maximum": 50,
                "Weight": 0
            }),
            ui.Label({"Text": "字", "Weight": 0}),
            ui.HGap(15),
            ui.Label({"Text": "<font color='#888888'>* 优先在标点处自然断句，长句按设定字数均匀拆分</font>", "Weight": 1}),
        ]),

        # 5. 台词片段列表与勾选工具栏
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "<b>时间线台词片段列表 (可单独勾选配音)：</b>", "Weight": 1}),
            ui.Button({"ID": "SelectAllBtn", "Text": "全选", "Weight": 0}),
            ui.HGap(6),
            ui.Button({"ID": "DeselectAllBtn", "Text": "取消全选", "Weight": 0}),
            ui.HGap(6),
            ui.Button({"ID": "InvertBtn", "Text": "反选", "Weight": 0}),
        ]),
        ui.Tree({"ID": "ClipTree", "Weight": 1.3}),

        # 6. 单句发音修正输入栏 (不修改原字幕只作用于读音)
        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "发音纠错 (仅修改朗读，不改原字幕):", "Weight": 0}),
            ui.LineEdit({
                "ID": "PhoneticEdit",
                "PlaceholderText": "在列表中点击选中任意台词，在此修改纠正发音或多音字...",
                "Weight": 1
            }),
            ui.HGap(6),
            ui.Button({"ID": "ApplyPhoneticBtn", "Text": "应用读音修改", "Weight": 0}),
            ui.HGap(6),
            ui.Button({"ID": "ResetPhoneticBtn", "Text": "恢复原台词", "Weight": 0}),
        ]),

        # 7. 实时日志预览窗口
        ui.Label({"Text": "<b>操作日志与运行状态：</b>", "Weight": 0}),
        ui.TextEdit({
            "ID": "LogBox",
            "Weight": 0.8,
            "ReadOnly": True,
            "Font": ui.Font({"Family": "Menlo", "PixelSize": 11})
        }),

        # 8. 底部按钮与状态
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
    auto_split_check = win.Find("AutoSplitCheck")
    split_char_spin = win.Find("SplitCharSpin")
    select_all_btn = win.Find("SelectAllBtn")
    deselect_all_btn = win.Find("DeselectAllBtn")
    invert_btn = win.Find("InvertBtn")
    clip_tree = win.Find("ClipTree")
    phonetic_edit = win.Find("PhoneticEdit")
    apply_phonetic_btn = win.Find("ApplyPhoneticBtn")
    reset_phonetic_btn = win.Find("ResetPhoneticBtn")
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
    clip_tree.ColumnCount = 5
    clip_tree.SetHeaderLabels(["勾选", "来源轨道", "时间码范围 (帧)", "原字幕内容", "配音读音文本 (选中可改读法)"])
    clip_tree.ColumnWidth[0] = 70
    clip_tree.ColumnWidth[1] = 130
    clip_tree.ColumnWidth[2] = 180
    clip_tree.ColumnWidth[3] = 250
    clip_tree.ColumnWidth[4] = 270

    scanned_items = []
    tree_rows = []
    current_edit_idx = None

    def update_selected_count_label():
        sel_count = sum(1 for r in tree_rows if r.CheckState[0] == "Checked")
        total = len(tree_rows)
        status_label.Text = f"已就绪：已勾选 {sel_count} / {total} 条文字片段"

    def refresh_scanned_items():
        nonlocal scanned_items, tree_rows, current_edit_idx
        clip_tree.Clear()
        tree_rows.clear()
        current_edit_idx = None
        phonetic_edit.Text = ""

        log("正在扫描时间线字幕轨与 Text+ / 标题片段...")
        scanned_items = extract_timeline_texts(timeline, resolve=resolve)
        if not scanned_items:
            log("[警告] 未在当前时间线上检测到任何填有文本的字幕或标题片段！")
            status_label.Text = "<font color='#EF4444'>未检测到任何文字片段，请确保时间线上有 Text+、标题或字幕轨且已输入文本</font>"
            return

        for idx, item in enumerate(scanned_items, 1):
            item["spoken_text"] = item.get("spoken_text") or item["text"]
            row = clip_tree.NewItem()
            row.Text[0] = str(idx)
            row.CheckState[0] = "Checked"
            row.Text[1] = f"{item['track_name']} ({item['track_type']})"
            row.Text[2] = f"{item['start_frame']} ~ {item['end_frame']} ({item['duration_frames']}帧)"
            row.Text[3] = item["text"]
            row.Text[4] = item["spoken_text"]
            clip_tree.AddTopLevelItem(row)
            tree_rows.append(row)

        msg = f"扫描完毕：共找到 {len(scanned_items)} 条文字片段。"
        log(f"[成功] {msg}")
        update_selected_count_label()

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

    def on_select_all(ev):
        for r in tree_rows:
            r.CheckState[0] = "Checked"
        update_selected_count_label()
        log("[选择] 已全选所有台词片段")

    def on_deselect_all(ev):
        for r in tree_rows:
            r.CheckState[0] = "Unchecked"
        update_selected_count_label()
        log("[选择] 已取消全选所有台词片段")

    def on_invert_selection(ev):
        for r in tree_rows:
            is_chk = (r.CheckState[0] == "Checked")
            r.CheckState[0] = "Unchecked" if is_chk else "Checked"
        update_selected_count_label()
        log("[选择] 已反选台词片段勾选状态")

    def on_tree_item_clicked(ev):
        nonlocal current_edit_idx
        item = ev.get("item")
        if not item:
            return
        idx = clip_tree.IndexOfTopLevelItem(item)
        if 0 <= idx < len(scanned_items):
            current_edit_idx = idx
            target_text = scanned_items[idx].get("spoken_text") or scanned_items[idx].get("text", "")
            phonetic_edit.Text = target_text
            status_label.Text = f"正在编辑第 {idx + 1} 条台词发音修正..."

    def on_tree_item_changed(ev):
        update_selected_count_label()

    def on_apply_phonetic(ev):
        nonlocal current_edit_idx
        if current_edit_idx is None or not (0 <= current_edit_idx < len(scanned_items)):
            log("[提示] 请先在列表中点击选中一条需要修改读音的台词片段")
            return
        new_text = phonetic_edit.Text.strip()
        if not new_text:
            log("[警告] 读音修正文本不能为空！")
            return
        scanned_items[current_edit_idx]["spoken_text"] = new_text
        orig_text = scanned_items[current_edit_idx]["text"]
        row = tree_rows[current_edit_idx]
        if new_text != orig_text:
            row.Text[4] = f"{new_text} [已纠正]"
        else:
            row.Text[4] = new_text
        log(f"[修正] 第 {current_edit_idx + 1} 条读音已修正为: \"{new_text}\" (原字幕内容保持不变)")

    def on_reset_phonetic(ev):
        nonlocal current_edit_idx
        if current_edit_idx is None or not (0 <= current_edit_idx < len(scanned_items)):
            log("[提示] 请先在列表中点击选中一条需要恢复读音的台词片段")
            return
        orig_text = scanned_items[current_edit_idx]["text"]
        scanned_items[current_edit_idx]["spoken_text"] = orig_text
        tree_rows[current_edit_idx].Text[4] = orig_text
        phonetic_edit.Text = orig_text
        log(f"[恢复] 第 {current_edit_idx + 1} 条已恢复原字幕读音: \"{orig_text}\"")

    def on_generate(ev):
        if not is_engine_online():
            show_native_alert("提示", "MamboTTS 引擎尚未运行！请先启动引擎。", is_error=True)
            return
        if not scanned_items:
            show_native_alert("提示", "当前没有检测到任何台词文本，无法配音！", is_error=True)
            return

        # 筛选勾选的台词
        items_to_process = []
        for idx, (item, row) in enumerate(zip(scanned_items, tree_rows)):
            if row.CheckState[0] == "Checked":
                items_to_process.append((idx + 1, item))

        if not items_to_process:
            log("[警告] 未在列表中勾选任何台词片段！请勾选至少一条片段后再开始生成。")
            show_native_alert("未勾选台词", "请在列表中勾选至少一条需要配音的台词片段！", is_error=False)
            return

        speed_val = speeds[speed_combo.CurrentIndex][1]
        sel_track_idx = track_combo.CurrentIndex
        do_auto_trim = bool(auto_trim_check.Checked)
        align_mode = "left" if align_combo.CurrentIndex == 0 else "right"
        allow_new_track_on_overlap = bool(overlap_track_check.Checked)
        do_auto_split = bool(auto_split_check.Checked)
        max_split_chars = int(split_char_spin.Value or 8)
        initial_timecode = timeline.GetCurrentTimecode()

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

        total = len(items_to_process)
        success_count = 0
        align_text = "左对齐" if align_mode == "left" else "右对齐"
        trim_desc = f"自动裁剪/延长文字轨 ({align_text})" if do_auto_trim else "保持文字原长"
        split_desc = f" | 按 {max_split_chars} 字自动拆分轨道" if do_auto_split else ""
        overlap_desc = "新建分轨放置" if allow_new_track_on_overlap else "默认同轨覆盖"

        log(f"开始批量处理勾选的 {total} 个片段 | 语速: {speed_val}x | {trim_desc}{split_desc} | 重叠处理: {overlap_desc}")

        # 记录已分配轨道的占用区间: {track_index: [(start_frame, end_frame), ...]}
        allocated_intervals = {base_target_track: []}

        for i, (orig_no, item) in enumerate(items_to_process, 1):
            spoken_text = item.get("spoken_text") or item["text"]
            short_spoken = spoken_text[:20] + ("..." if len(spoken_text) > 20 else "")
            status_label.Text = f"正在处理 [{i}/{total}]: {short_spoken}"
            if spoken_text != item["text"]:
                log(f"[{i}/{total}] 调用 GPT-SoVITS 合成纠正读音: 「{short_spoken}」(原文字: {item['text']})")
            else:
                log(f"[{i}/{total}] 调用 GPT-SoVITS 合成: 「{short_spoken}」")

            wav_name = f"mambo_{item['start_frame']}_{orig_no}.wav"
            wav_path = os.path.join(cache_dir, wav_name)

            ok, err_msg = synthesize_speech(spoken_text, wav_path, speed=speed_val)
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
                    if dur_frames < text_dur:
                        align_action = f"左对齐裁剪：文字将从 {text_dur} 帧裁剪至 {dur_frames} 帧"
                    elif dur_frames > text_dur:
                        align_action = f"左对齐延长：文字将从 {text_dur} 帧自动延长至 {dur_frames} 帧"
                    else:
                        align_action = "左对齐：文字与音频时长完全吻合"
                    log(f"[对齐] {align_action} (帧 {record_frame} ~ {record_frame + dur_frames})")
                else:
                    # 右对齐
                    record_frame = max(0, text_end - dur_frames)
                    if dur_frames < text_dur:
                        align_action = f"右对齐裁剪：文字将从 {text_dur} 帧裁剪至 {dur_frames} 帧"
                    else:
                        align_action = "右对齐：以终点为基准对齐"
                    log(f"[对齐] {align_action} (帧 {record_frame} ~ {text_end})")
            else:
                record_frame = text_start

            audio_end_frame = record_frame + dur_frames

            # 3. 重叠检测与轨道分配
            if not allow_new_track_on_overlap:
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

            res_track_type = "subtitle" if item["track_type"] == "subtitle" else "video"

            # 5. 执行文字轨道物理对齐 (智能裁剪或延长)
            aligned_clip_end = text_end
            if do_auto_trim:
                if dur_frames < text_dur:
                    # 音频短于文字：裁剪缩减文字片段
                    if align_mode == "left":
                        cut_frame = text_start + dur_frames
                        is_tail = True
                        aligned_clip_end = cut_frame
                    else:
                        cut_frame = record_frame
                        is_tail = False
                        aligned_clip_end = text_end

                    trim_ok = trim_timeline_clip(
                        timeline=timeline,
                        track_type=res_track_type,
                        track_index=item["track_index"],
                        clip_start=text_start,
                        clip_end=text_end,
                        cut_frame=cut_frame,
                        fps=fps,
                        is_tail=is_tail,
                        log_fn=log,
                    )
                    if not trim_ok and item["track_type"] == "video_textplus" and item.get("clip_obj"):
                        # 备用降级方案：调整 Fusion 内部渲染有效范围
                        try:
                            comp = item["clip_obj"].GetFusionCompByIndex(1)
                            if comp:
                                if is_tail:
                                    comp.SetAttrs({
                                        "COMPN_RenderEnd": float(min(text_dur - 1, dur_frames - 1)),
                                        "COMPN_GlobalEnd": float(min(text_dur - 1, dur_frames - 1)),
                                    })
                                else:
                                    comp.SetAttrs({
                                        "COMPN_RenderStart": float(max(0, text_dur - dur_frames)),
                                        "COMPN_GlobalStart": float(max(0, text_dur - dur_frames)),
                                    })
                        except Exception as e:
                            write_log(f"备用调整 Fusion 范围出错: {e}")

                elif dur_frames > text_dur:
                    # 音频长于文字：自动延长文字片段至音频结束
                    if align_mode == "left":
                        target_end = text_start + dur_frames
                        aligned_clip_end = target_end
                        extend_timeline_clip(
                            timeline=timeline,
                            track_type=res_track_type,
                            track_index=item["track_index"],
                            clip_start=text_start,
                            clip_end=text_end,
                            target_end=target_end,
                            fps=fps,
                            log_fn=log,
                        )
                        if item["track_type"] == "video_textplus" and item.get("clip_obj"):
                            try:
                                comp = item["clip_obj"].GetFusionCompByIndex(1)
                                if comp:
                                    comp.SetAttrs({
                                        "COMPN_RenderEnd": float(dur_frames - 1),
                                        "COMPN_GlobalEnd": float(dur_frames - 1),
                                    })
                            except Exception as e:
                                write_log(f"更新 Text+ Fusion 渲染范围出错: {e}")
                    else:
                        log(f"[提示] 右对齐模式下音频长于文字，已以文字终点为基准对齐 (帧 {record_frame} ~ {text_end})")
                else:
                    aligned_clip_end = text_end
                    log(f"[对齐] 音频时长 ({dur_frames}帧) 与文字原长完全一致，无需调整")

            # 6. 执行按指定字数智能拆分字幕轨道 (先对齐后拆分编辑)
            if do_auto_split:
                split_timeline_clip_by_length(
                    timeline=timeline,
                    track_type=res_track_type,
                    track_index=item["track_index"],
                    clip_start=text_start,
                    clip_end=aligned_clip_end,
                    text=item["text"],
                    max_chars=max_split_chars,
                    fps=fps,
                    log_fn=log,
                )

        # 恢复播放头初始位置
        if initial_timecode:
            try:
                timeline.SetCurrentTimecode(initial_timecode)
            except Exception:
                pass

        # 刷新时间线片段列表
        refresh_scanned_items()

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
    win.On["SelectAllBtn"].Clicked = on_select_all
    win.On["DeselectAllBtn"].Clicked = on_deselect_all
    win.On["InvertBtn"].Clicked = on_invert_selection
    win.On["ApplyPhoneticBtn"].Clicked = on_apply_phonetic
    win.On["ResetPhoneticBtn"].Clicked = on_reset_phonetic
    win.On["ClipTree"].ItemClicked = on_tree_item_clicked
    win.On["ClipTree"].ItemDoubleClicked = on_tree_item_clicked
    win.On["ClipTree"].CurrentItemChanged = on_tree_item_clicked
    win.On["ClipTree"].ItemChanged = on_tree_item_changed

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
