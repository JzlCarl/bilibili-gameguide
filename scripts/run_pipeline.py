"""
=====================================================================
B站视频游戏攻略 · 主入口
=====================================================================
运行完整 pipeline：

    python run_pipeline.py [config_path]

Pipeline 步骤：
    Step 1: 解析 SRT，为各章节填充字幕片段
    Step 2: FFmpeg 截图（首帧 + 采样帧 + 末帧）
    Step 3: 生成最终 HTML
    Step 4: 生成完整 Markdown 笔记（可选，生成后跳过不影响流程）

注意：视频文件不再自动清理，保留在任务目录中供后续使用。

配置文件（config.json）包含所有视频相关参数和截图参数，
脚本本身不含任何硬编码。
=====================================================================
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def run_step(name: str, script: str, config: Path):
    cmd = ["python", str(script), str(config)]
    print(f"\n{'='*60}")
    print(f"▶ {name}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def main():
    config = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    if not config.exists():
        print(f"错误: 配置文件不存在: {config}")
        print(f"请创建 config.json（参考 config_template.json）")
        sys.exit(1)

    # 检查结构文件存在（优先 _with_subs 版本）
    import json
    with open(config, encoding="utf-8") as f:
        cfg = json.load(f)
    config_dir = config.parent.resolve()
    paths_cfg = cfg.get("paths", {})
    struct_with_subs = config_dir / paths_cfg.get("structure_with_subs_file", "video_structure_with_subs.json")
    struct_plain = config_dir / paths_cfg.get("structure_file", "video_structure.json")
    if not struct_with_subs.exists() and not struct_plain.exists():
        print(f"错误: 语义结构文件不存在")
        print(f"  请先由 LLM 基于字幕生成 video_structure_with_subs.json（写入工作目录）")
        sys.exit(1)

    rc1 = run_step("Step 1: SRT 解析 & 字幕填充",
                   SCRIPT_DIR / "step1_parse_srt.py", config)
    if rc1 != 0:
        print(f"\nStep 1 失败 (exit {rc1})。")
        sys.exit(rc1)

    rc2 = run_step("Step 2: FFmpeg 截图",
                   SCRIPT_DIR / "step2_screenshot.py", config)
    if rc2 != 0:
        print(f"\nStep 2 失败 (exit {rc2})。")
        sys.exit(rc2)

    rc3 = run_step("Step 3: HTML 生成",
                   SCRIPT_DIR / "step3_generate_html.py", config)
    if rc3 != 0:
        print(f"\nStep 3 失败 (exit {rc3})。")
        sys.exit(rc3)

    # Step 4: Markdown 笔记（可选，失败不中断）
    rc4 = run_step("Step 4: Markdown 完整笔记（可选）",
                   SCRIPT_DIR / "step4_generate_markdown.py", config)
    if rc4 != 0:
        print(f"\n[WARN] Step 4 Markdown 生成失败 (exit {rc4})，但不影响 HTML 输出。")

    print("\n\n" + "="*60)
    print("✅ Pipeline 完成！")
    print("   · game_guide.html    — 图文攻略（暗色主题，可离线分享）")
    print("   · *_full_notes.md    — 完整 Markdown 笔记")
    print("   · 原视频已保留在任务目录中")
    print("="*60)


if __name__ == "__main__":
    main()

