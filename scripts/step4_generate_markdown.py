#!/usr/bin/env python3
"""
生成完整图文笔记 Markdown 文件
综合 video_structure_with_subs.json（分级标题+字幕原文）和 screenshot_mapping.json（截图引用）
"""

import json
from pathlib import Path
from datetime import datetime

def build_timestamp(sub):
    """格式化时间戳 HH:MM:SS"""
    s = int(sub.get("start", 0))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"

def subtitles_to_text(subs):
    """将字幕列表合并为可读文本"""
    if not subs:
        return ""
    return "".join(f"{build_timestamp(s)} {s['text']}" for s in subs)

def find_screenshots_for_subsection(subsections_id, mapping):
    """根据 subsection id 查找对应截图"""
    # 从 heading 提取 subsection 标题
    results = []
    for item in mapping:
        sub_heading = item.get("subsection", "")
        if sub_heading.replace("### ", "") in subsections_id.replace("### ", ""):
            results.extend(item.get("screenshots", []))
    return results

def generate_full_markdown(structure_path, mapping_path, output_path):
    """生成完整 Markdown 文件"""

    with open(structure_path, "r", encoding="utf-8") as f:
        structure = json.load(f)

    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # 构建截图查找表 {时间戳: screenshot_info}
    screenshot_lookup = {}
    for item in mapping:
        for sc in item.get("screenshots", []):
            ts = sc.get("timestamp", 0)
            screenshot_lookup[ts] = {
                "filename": sc.get("filename", ""),
                "reason": sc.get("reason", ""),
                "subtitle_hint": sc.get("subtitle_hint", ""),
                "subsection": item.get("subsection", "")
            }

    lines = []

    # ========== 标题区 ==========
    title = structure.get("video_title", "视频笔记")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> 来源: [{title}]({structure.get('video_url', '')})")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 目录 ==========
    lines.append("## 目录")
    lines.append("")
    for section in structure.get("sections", []):
        heading = section.get("heading", "").replace("## ", "")
        lines.append(f"- [{heading}](#{section.get('id', '')})")
        for sub in section.get("subsections", []):
            sub_heading = sub.get("heading", "").replace("### ", "")
            lines.append(f"  - [{sub_heading}](#{sub.get('id', '')})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ========== 内容区 ==========
    for section in structure.get("sections", []):
        section_id = section.get("id", "")
        section_heading = section.get("heading", "")
        section_summary = section.get("concise_summary", "")
        section_bullets = section.get("bullet_points", [])
        section_subs = section.get("subtitles", [])

        # 主标题
        lines.append(section_heading)
        lines.append("")
        lines.append(f"**精炼摘要:** {section_summary}")
        lines.append("")
        if section_bullets:
            lines.append("**关键要点:**")
            for bp in section_bullets:
                lines.append(f"- {bp}")
            lines.append("")

        # 主章节截图
        section_screenshots = [s for ts, s in screenshot_lookup.items()
                              if section.get("start_sec", 0) <= ts <= section.get("end_sec", 0)]
        if section_screenshots:
            lines.append("**截图:**")
            for sc in section_screenshots:
                img_path = f"./screenshots/{sc['filename']}"
                lines.append(f"![{sc['filename']}]({img_path})")
            lines.append("")

        # 主章节字幕原文
        if section_subs:
            lines.append("**字幕原文:**")
            lines.append("")
            for sub in section_subs:
                ts_str = build_timestamp(sub)
                text = sub.get("text", "")
                lines.append(f"[{ts_str}] {text}")
            lines.append("")

        lines.append("---")
        lines.append("")

        # 子章节
        for subsection in section.get("subsections", []):
            sub_id = subsection.get("id", "")
            sub_heading = subsection.get("heading", "")
            sub_summary = subsection.get("concise_summary", "")
            sub_bullets = subsection.get("bullet_points", [])
            sub_subs = subsection.get("subtitles", [])

            # 子标题
            lines.append(sub_heading)
            lines.append("")
            lines.append(f"**精炼摘要:** {sub_summary}")
            lines.append("")
            if sub_bullets:
                lines.append("**关键要点:**")
                for bp in sub_bullets:
                    lines.append(f"- {bp}")
                lines.append("")

            # 子章节截图
            sub_screenshots = [s for ts, s in screenshot_lookup.items()
                              if subsection.get("start_sec", 0) <= ts <= subsection.get("end_sec", 0)]
            if sub_screenshots:
                lines.append("**截图:**")
                for sc in sub_screenshots:
                    img_path = f"./screenshots/{sc['filename']}"
                    reason_map = {"first": "开始", "change": "转折", "last": "结尾"}
                    reason_text = reason_map.get(sc.get("reason", ""), sc.get("reason", ""))
                    lines.append(f"![{sc['filename']}]({img_path}) *{reason_text}: {sc.get('subtitle_hint', '')}*")
                lines.append("")

            # 子章节字幕原文
            if sub_subs:
                lines.append("**字幕原文:**")
                lines.append("")
                for sub in sub_subs:
                    ts_str = build_timestamp(sub)
                    text = sub.get("text", "")
                    lines.append(f"[{ts_str}] {text}")
                lines.append("")

            lines.append("")
            lines.append("---")
            lines.append("")

    # ========== 底部统计 ==========
    total_screenshots = sum(len(item.get("screenshots", [])) for item in mapping)
    total_subs = sum(len(s.get("subtitles", [])) for s in structure.get("sections", []))
    total_subs += sum(len(sub.get("subtitles", []))
                      for section in structure.get("sections", [])
                      for sub in section.get("subsections", []))

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 统计信息")
    lines.append("")
    lines.append(f"- 主章节数: {len(structure.get('sections', []))}")
    lines.append(f"- 子章节数: {sum(len(s.get('subsections', [])) for s in structure.get('sections', []))}")
    lines.append(f"- 截图数量: {total_screenshots}")
    lines.append(f"- 字幕片段: {total_subs}")
    lines.append(f"- 视频时长: {structure.get('sections', [{}])[-1].get('end_sec', 0):.0f} 秒")

    # 写入文件
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 生成完成: {output_path}")
    print(f"     章节: {len(structure.get('sections', []))} 主 + {sum(len(s.get('subsections', [])) for s in structure.get('sections', []))} 子")
    print(f"     截图: {total_screenshots} 张")
    print(f"     字幕片段: {total_subs} 条")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成完整图文笔记 Markdown")
    parser.add_argument("config", help="config.json 路径")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config_dir = Path(args.config).parent.resolve()
    video = config.get("video", {})
    paths = config.get("paths", {})

    video_name = video.get("title", "video")

    generate_full_markdown(
        structure_path=config_dir / paths.get("structure_with_subs_file", "video_structure_with_subs.json"),
        mapping_path=config_dir / paths.get("mapping_file", "screenshot_mapping.json"),
        output_path=config_dir / f"{video_name}_full_notes.md"
    )
