"""
=====================================================================
B站视频游戏攻略 · Step 1：SRT 字幕解析
=====================================================================
从 config.json 读取配置，解析 SRT 字幕文件，
为 video_structure.json 中的每个 section 填充原始字幕片段。

工作原理：
  1. 解析 SRT（支持 , 和 . 毫秒分隔符，剔除 HTML 标签）
  2. 按时间窗口匹配字幕到各章节
  3. 输出 video_structure_with_subs.json（仅用于截图阶段参考）

用法：
    python step1_parse_srt.py [config_path]
    # 默认读取同目录下的 config.json
=====================================================================
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


# ------------------------------------------------------------------ #
# 时间工具                                                          #
# ------------------------------------------------------------------ #

def ts_to_sec(ts_str: str) -> int:
    """00:00:00,260 → 秒（取整），兼容 , 或 . 分隔毫秒"""
    ts = ts_str.replace(",", ".").strip()
    if "." in ts:
        main_part, ms = ts.rsplit(".", 1)
    else:
        main_part, ms = ts, "0"
    h, m, s = main_part.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) // 1000


def sec_to_ts(s: float | int) -> str:
    """秒 → MM:SS"""
    s = max(0, int(s))
    return f"{s // 60:02d}:{s % 60:02d}"


# ------------------------------------------------------------------ #
# SRT 解析                                                          #
# ------------------------------------------------------------------ #

def parse_srt(filepath: str) -> list[dict]:
    """解析 SRT，返回 [{start, end, text}, ...]"""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    blocks = re.findall(
        r"(\d+)\n"
        r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\n"
        r"([\s\S]+?)"
        r"(?=\n\n\d+\n|\n\n$)",
        content
    )

    subs = []
    for seq, start_ts, end_ts, raw_text in blocks:
        text = re.sub(r"<[^>]+>", "", raw_text).strip()
        if not text:
            continue
        s = ts_to_sec(start_ts)
        e = ts_to_sec(end_ts)
        subs.append({"start": s, "end": e, "text": text})
    return subs


# ------------------------------------------------------------------ #
# 主逻辑                                                            #
# ------------------------------------------------------------------ #

def run(config_path: str | Path | None = None) -> str:
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    video_cfg = cfg["video"]
    paths_cfg = cfg["paths"]
    config_dir = config_path.parent.resolve()

    srt_path = config_dir / video_cfg["subtitle"]
    if not srt_path.exists():
        raise FileNotFoundError(f"字幕文件不存在: {srt_path}")

    # 优先用 structure_with_subs_file（新流程，LLM 直接输出此名），
    # 没有则退而用 structure_file（旧流程）
    struct_path = config_dir / paths_cfg.get(
        "structure_with_subs_file", "video_structure_with_subs.json"
    )
    if not struct_path.exists():
        struct_path = config_dir / paths_cfg.get("structure_file", "video_structure.json")
    if not struct_path.exists():
        raise FileNotFoundError(
            f"语义结构文件不存在: {struct_path}，"
            "请先由 LLM 基于字幕生成 video_structure_with_subs.json。"
        )

    with open(struct_path, encoding="utf-8") as f:
        structure = json.load(f)

    print(f"解析 SRT: {srt_path}")
    subs = parse_srt(str(srt_path))
    print(f"  -> 共 {len(subs)} 个字幕块")

    # 按时间窗口匹配字幕到章节
    def fill_subs(all_subs: list, start: int, end: int) -> list:
        return [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in all_subs
            if s["start"] < end and s["end"] > start
        ]

    for section in structure.get("sections", []):
        if section.get("subsections"):
            for subsec in section["subsections"]:
                subsec["subtitles"] = fill_subs(subs, subsec["start_sec"], subsec["end_sec"])
            section["subtitles"] = [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for subsec in section["subsections"]
                for s in subsec.get("subtitles", [])
            ]
        else:
            section["subtitles"] = fill_subs(subs, section["start_sec"], section["end_sec"])

    out_path = config_dir / paths_cfg.get(
        "structure_with_subs_file", "video_structure_with_subs.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(structure, f, ensure_ascii=False, indent=2)

    total_subs = sum(len(s.get("subtitles", [])) for s in structure.get("sections", []))
    print(f"\n字幕填充完成:")
    print(f"  -> 输出: {out_path}")
    print(f"  -> {len(structure['sections'])} 个 ## 段落")
    print(f"  -> {sum(len(s.get('subsections', [])) for s in structure['sections'])} 个 ### 子段落")
    print(f"  -> {total_subs} 条字幕记录")
    return str(out_path)


if __name__ == "__main__":
    cfg_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(cfg_arg)
