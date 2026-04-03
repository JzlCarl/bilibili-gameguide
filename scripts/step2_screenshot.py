"""
=====================================================================
bilibili-gameguide · Step 2：CV 感知哈希截图
=====================================================================
从 config.json 读取配置（cv 参数 / paths）。
从 video_structure_with_subs.json 读取语义结构。
对每个 ### 最小段落截图：首帧 + CV 变化帧 + 末帧。
跨段边界用感知哈希检测"内容切换点"，而非粗暴偏移。

依赖（优先从 ~/.workbuddy/tools/ 查找）：
    pip install opencv-python imagehash Pillow

用法：
    python step2_screenshot.py [config_path]
    # 默认读取同目录下的 config.json
=====================================================================
"""

import json
import re
import sys
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"

# 复用统一工具查找（Layer 0/1/2，自动注册）
from check_dependencies import find_tool


def find_executable(name: str) -> str:
    """通过 check_dependencies.find_tool() 找工具。"""
    found = find_tool(name.lower())
    return str(found) if found else name


# ------------------------------------------------------------------ #
# 配置加载                                                          # #
# ------------------------------------------------------------------ #

def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve(cfg: dict, key: str, config_dir: Path) -> Path:
    """返回绝对路径：相对路径相对于 config.json 所在目录。"""
    val = cfg[key]
    p = Path(val)
    return p if p.is_absolute() else (config_dir / p).resolve()


# ------------------------------------------------------------------ #
# 时间工具                                                          # #
# ------------------------------------------------------------------ #

def sec_to_ts(s: float | int) -> str:
    s = max(0, int(s))
    return f"{s // 60:02d}:{s % 60:02d}"


# ------------------------------------------------------------------ #
# CV 感知哈希工具                                                    #
# ------------------------------------------------------------------ #

def get_frame_at(video_cap, sec: float) -> np.ndarray | None:
    """跳转到指定秒数，返回 BGR 帧。"""
    video_cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
    ret, frame = video_cap.read()
    return frame if ret else None


def extract_features(frame: np.ndarray):
    """
    提取三个特征：
      - pHash：感知哈希，感知相似性
      - 直方图：颜色分布
      - Laplacian 方差：清晰度/边缘密度
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    pil  = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    ph   = imagehash.phash(pil)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    hist = hist / hist.sum()
    lap  = cv2.Laplacian(gray, cv2.CV_64F).var()
    return ph, hist, lap


def ph_diff(h1, h2) -> int:
    if h1 is None or h2 is None:
        return float("inf")
    return int(h1 != h2)


def hist_diff(h1, h2) -> float:
    if h1 is None or h2 is None:
        return float("inf")
    return float(np.sum(np.abs(h1 - h2)))


# ------------------------------------------------------------------ #
# 截图策略                                                          #
# ------------------------------------------------------------------ #

def find_best_frame_in_window(video_cap, start_sec: float, end_sec: float,
                               last_ph, last_hist, cv_cfg: dict) -> float | None:
    """
    在 [start_sec, end_sec] 窗口内，从前往后扫，
    找到第一个与 last_ph/last_hist 有显著差异的帧。
    返回该帧的时间戳，或 None（窗口内无显著变化）。
    """
    PH_THRESH  = cv_cfg["pHash_threshold"]
    HIST_THRESH = cv_cfg["hist_threshold"]
    LAP_THRESH  = cv_cfg["laplacian_threshold"]

    sec = start_sec
    while sec <= end_sec:
        frame = get_frame_at(video_cap, sec)
        if frame is None:
            sec += cv_cfg["frame_interval_sec"]
            continue
        ph, hist, lap = extract_features(frame)
        ph_d   = ph_diff(ph, last_ph)
        hist_d = hist_diff(hist, last_hist)
        if ph_d > PH_THRESH or hist_d > HIST_THRESH or (lap > LAP_THRESH and hist_d > HIST_THRESH * 0.5):
            return sec
        sec += cv_cfg["frame_interval_sec"]
    return None


def select_screenshots(video_cap, start_sec: float, end_sec: float,
                       last_ph, last_hist, cv_cfg: dict) -> list[float]:
    """
    为单个时间段选择截图时间点。
    策略：首帧 + 中间变化帧（最多 MAX_PER_WINDOW 个）+ 末帧（若与最后变化帧不重复）。
    """
    MIN_GAP    = cv_cfg["min_gap_sec"]
    MIN_WINDOW = cv_cfg["min_window_sec"]
    MAX_PER    = cv_cfg["max_per_window"]

    if end_sec - start_sec < MIN_WINDOW:
        return [start_sec] if start_sec < end_sec else []

    result = []
    window_start = start_sec

    # 追踪最后一个选中帧的特征（用于末帧比较）
    last_selected_ph   = last_ph
    last_selected_hist = last_hist

    while window_start < end_sec:
        hit = find_best_frame_in_window(
            video_cap, window_start, end_sec,
            last_selected_ph, last_selected_hist, cv_cfg
        )
        if hit is None:
            break
        result.append(hit)
        # 提取该帧特征用于下次比较
        frame = get_frame_at(video_cap, hit)
        if frame is not None:
            hit_ph, hit_hist, _ = extract_features(frame)
            last_selected_ph   = hit_ph
            last_selected_hist = hit_hist
        window_start = hit + MIN_GAP
        if len(result) >= MAX_PER:
            break

    # 末帧（若与最后选中帧有明显差异）
    last_frame_ts = max(start_sec, end_sec - 2)
    if result and (last_frame_ts - result[-1]) >= MIN_GAP:
        frame = get_frame_at(video_cap, last_frame_ts)
        if frame is not None:
            ph, hist, _ = extract_features(frame)
            if ph_diff(ph, last_selected_ph) > 5 or \
               hist_diff(hist, last_selected_hist) > 0.05:
                result.append(last_frame_ts)

    # 去重（同一秒内）
    seen = set()
    deduped = []
    for t in result:
        key = round(t)
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    return deduped


# ------------------------------------------------------------------ #
# 边界检测：找"内容切换点"                                            #
# ------------------------------------------------------------------ #

def find_boundary_frame(video_cap, prev_end_sec: float,
                        curr_start_sec: float, curr_end_sec: float,
                        prev_ph, prev_hist, cv_cfg: dict) -> float:
    """
    在 curr_start_sec ~ curr_end_sec 区间内，从前往后扫描，
    返回第一个与 prev_ph/prev_hist 有显著视觉差异的帧。
    这才是 curr 段的真实首帧。
    """
    BOUND_PH   = cv_cfg.get("boundary_pHash_threshold", 10)
    BOUND_HIST = cv_cfg.get("boundary_hist_threshold", 0.15)
    INTERVAL   = cv_cfg["frame_interval_sec"]

    sec = curr_start_sec
    while sec <= curr_end_sec:
        frame = get_frame_at(video_cap, sec)
        if frame is None:
            sec += INTERVAL
            continue
        ph, hist, _ = extract_features(frame)
        ph_d   = ph_diff(ph, prev_ph)
        hist_d = hist_diff(hist, prev_hist)
        if ph_d > BOUND_PH or hist_d > BOUND_HIST:
            return sec
        sec += INTERVAL
    return curr_start_sec  # 没找到变化 → 保守返回原起始


# ------------------------------------------------------------------ #
# 字幕工具（用于截图文件名注释）                                       #
# ------------------------------------------------------------------ #

def parse_srt_for_mapping(srt_path: Path) -> list[dict]:
    """解析 SRT，返回 [{start: int(秒), text: str}] 列表。"""
    if not srt_path.exists():
        return []
    with open(srt_path, encoding="utf-8") as f:
        raw = f.read()
    subs = []
    for block in re.findall(
        r"(\d+)\n"
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n"
        r"([\s\S]+?)(?=\n\n\d+\n|\n\n$)",
        raw
    ):
        text = re.sub(r"<[^>]+>", "", block[3]).strip()
        if not text:
            continue
        ts_clean = block[1].replace(",", ".")
        main, ms = ts_clean.rsplit(".", 1)
        h, m, s = main.split(":")
        secs = int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) // 1000
        subs.append({"start": secs, "text": text})
    return subs


def get_nearest_subtitle_text(subs: list[dict], ts: float) -> str:
    if not subs:
        return ""
    best = min(subs, key=lambda s: abs(s["start"] - ts))
    return best.get("text", "")[:60]


# ------------------------------------------------------------------ #
# 主逻辑                                                            #
# ------------------------------------------------------------------ #

def run(config_path: str | Path | None = None):
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    cfg = load_config(config_path)
    config_dir = config_path.parent.resolve()

    cv_cfg    = cfg["cv"]
    paths_cfg = cfg["paths"]

    video_path = resolve(cfg["video"], "file", config_dir)
    srt_path   = resolve(cfg["video"], "subtitle", config_dir)

    shots_dir = config_dir / paths_cfg["screenshots_dir"]
    shots_dir.mkdir(parents=True, exist_ok=True)

    struct_path = config_dir / paths_cfg.get(
        "structure_with_subs_file", "video_structure_with_subs.json"
    )
    if not struct_path.exists():
        raise FileNotFoundError(
            f"请先运行 step1_parse_srt.py 生成 {struct_path}"
        )

    with open(struct_path, encoding="utf-8") as f:
        structure = json.load(f)

    # 解析字幕（用于截图注释）
    subs = parse_srt_for_mapping(srt_path)

    # 打开视频
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"视频: {video_path.name}  ({total_frames} 帧 @ {fps:.1f}fps)")

    # 遍历语义结构：收集所有 ### 叶子段落
    all_segments = []
    for section in structure.get("sections", []):
        if section.get("subsections"):
            all_segments.extend(section["subsections"])
        else:
            all_segments.append(section)

    # 对相邻段做边界 CV 检测
    mapping = []
    prev_ph       = None
    prev_hist     = None
    prev_end_sec  = None
    # 全局截图序号
    global_idx    = 0

    for i, seg in enumerate(all_segments):
        seg_start = seg["start_sec"]
        seg_end   = seg["end_sec"]
        seg_label = seg.get("heading", seg.get("id", f"seg_{i}"))

        # 边界检测
        if prev_end_sec is not None:
            true_start = find_boundary_frame(
                cap, prev_end_sec, seg_start, seg_end,
                prev_ph, prev_hist, cv_cfg
            )
            if true_start > seg_start + 1.0:   # 有实质右移
                seg_start = true_start

        # 选帧
        if prev_ph is None:
            first_ph   = None
            first_hist = None
        else:
            first_ph   = prev_ph
            first_hist = prev_hist

        times = select_screenshots(
            cap, seg_start, seg_end, first_ph, first_hist, cv_cfg
        )
        if times and prev_end_sec is not None and abs(times[0] - prev_end_sec) < 2.0:
            times = times[1:]   # 去除与前段末帧重叠的帧

        # 截图
        seg_shots = []
        for t in times:
            global_idx += 1
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if not ret:
                continue
            fname = f"s{global_idx:04d}_{sec_to_ts(t).replace(':', '')}.jpg"
            fpath = shots_dir / fname
            cv2.imwrite(str(fpath), frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 88])
            ph, hist, lap = extract_features(frame)
            prev_ph      = ph
            prev_hist    = hist
            prev_end_sec = t
            seg_shots.append({
                "timestamp":     t,
                "filename":      fname,
                "reason":        "first" if t == times[0] else (
                                 "last" if t == times[-1] else "change"
                                 ),
                "subtitle_hint": get_nearest_subtitle_text(subs, t)
            })

        mapping.append({
            "subsection":  seg_label,
            "start_sec":   seg.get("start_sec"),
            "end_sec":     seg.get("end_sec"),
            "screenshots": seg_shots
        })
        print(f"  [{i+1}/{len(all_segments)}] {seg_label}: "
              f"{seg.get('start_sec')}s-{seg.get('end_sec')}s "
              f"-> {len(seg_shots)} 张截图")

    cap.release()

    # 保存 mapping
    mapping_path = config_dir / paths_cfg.get("mapping_file", "screenshot_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    total_shots = sum(len(m["screenshots"]) for m in mapping)
    print(f"\n截图完成: {mapping_path}")
    print(f"  -> 共 {total_shots} 张截图，分布在 {len(mapping)} 个段落")
    print(f"  -> 截图目录: {shots_dir}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
