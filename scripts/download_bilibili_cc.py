#!/usr/bin/env python3
"""
下载B站视频CC字幕工具（bilibili-gameguide 版）

工具定义（供 LLM 调用）：
download_bilibili_cc(url: str, output_dir: str) -> {
    success: bool,
    subtitle_file: str | None,
    video_title: str,
    char_count: int,
    content_preview: str,
    message: str
}

make_task_dir(base_dir: str, bv_id: str, video_title: str) -> str
  按规范 "BV号_视频名称_任务时间" 在 base_dir 下创建任务文件夹，返回路径。
  视频名称中的非法字符自动替换为下划线，超长部分截断。

返回的 subtitle_file 为 None 时表示字幕无效（内容与标题不相关），
此时 LLM 应告知用户无法继续（可仅下载视频，不走后续 pipeline）。
"""

import argparse
import json
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# 复用 check_dependencies.py 的统一查找逻辑（Layer 0/1/2 三层，自动注册到注册表）
from check_dependencies import find_tool, ensure_download_root, get_download_root


def find_exe(tool: str) -> Optional[str]:
    """
    通过 check_dependencies.find_tool() 查找工具。
    优先从已知路径注册表返回，找不到则退化到 PATH。
    不触发 conda/PowerShell profile，无 shell 依赖。
    """
    found = find_tool(tool.lower())
    if found:
        return str(found)
    # 退化：直接用名字碰 PATH
    try:
        r = subprocess.run([tool, "--help"], capture_output=True, text=True, timeout=5)
        if r.returncode in (0, 1):
            return tool
    except FileNotFoundError:
        pass
    return None


def sanitize_dirname(name: str, max_len: int = 40) -> str:
    """
    将视频标题转为合法的目录名片段：
    - 将 Windows/Linux 非法文件名字符（\\ / : * ? " < > |）替换为 _
    - 将连续空白/下划线压缩为单个 _
    - 截断至 max_len 字符（避免路径过长）
    - 去除首尾下划线/空格
    """
    # 替换非法字符
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 空白/换行 → 下划线
    cleaned = re.sub(r'\s+', '_', cleaned)
    # 连续下划线 → 单个
    cleaned = re.sub(r'_+', '_', cleaned)
    # 截断
    cleaned = cleaned[:max_len]
    # 去首尾下划线
    return cleaned.strip('_')


def make_task_dir(base_dir: Optional[str], bv_id: str, video_title: str) -> str:
    """
    在 base_dir 下创建任务目录，命名格式：{BV号}_{视频名称}_{任务时间}
    - BV号：从 URL 提取或直接传入
    - 视频名称：经过 sanitize_dirname 处理（去除非法字符，截断至40字）
    - 任务时间：yyyymmdd_HHMM

    base_dir 为 None 时自动读取设备配置的下载根目录；
    若尚未配置，则交互式引导用户指定（仅首次触发）。

    返回创建好的目录绝对路径。
    """
    # 确定下载根目录
    if base_dir:
        root = Path(base_dir)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = ensure_download_root(interactive=True)
        if not root:
            raise RuntimeError(
                "未配置下载根目录，且当前环境不支持交互式输入。\n"
                "请先运行：python check_dependencies.py --set-download-root <路径>"
            )

    # 提取 BV 号（兼容直接传入 BVxxx 或 URL 中含 BVxxx）
    bv_match = re.search(r'(BV[A-Za-z0-9]+)', bv_id or '', re.IGNORECASE)
    bv = bv_match.group(1) if bv_match else bv_id or 'BVunknown'

    title_part = sanitize_dirname(video_title or 'untitled')
    time_part = datetime.now().strftime('%Y%m%d_%H%M')

    dir_name = f"{bv}_{title_part}_{time_part}"
    task_dir = root / dir_name
    task_dir.mkdir(parents=True, exist_ok=True)
    return str(task_dir.resolve())


def extract_chinese_words(text: str) -> list[str]:
    """从文本中提取中文词（2-4字的连续中文字符序列），过滤常见无意义词。"""
    stopwords = {"的", "了", "是", "在", "和", "与", "或", "以及", "等", "之", "为",
                 "一个", "这个", "那个", "什么", "怎么", "如何", "有", "我", "你",
                 "他", "她", "它", "我们", "你们", "视频", "内容", "介绍", "关于",
                 "一下", "详解", "分析", "说明", "这里", "那么", "其实", "可能",
                 "就是", "还是", "可以", "不会", "应该", "觉得", "没有", "不是",
                 "但是", "所以", "如果", "因为", "已经", "开始", "然后", "这样",
                 "那样", "自己", "现在", "今天", "大家", "东西", "他们", "一种"}
    # 匹配连续2-4个中文字符
    words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
    return [w for w in words if w not in stopwords]


def check_content_relevance(video_title: str, subtitle_text: str) -> tuple[bool, str]:
    """
    用视频标题关键词和字幕内容做相关性检查。
    提取标题中的中文词（≥15%未命中）→ 判定不相关（ASR 串台）。
    """
    if not video_title or not subtitle_text:
        return True, "无标题，跳过相关性检查"

    words = extract_chinese_words(video_title)
    if len(words) < 3:
        return True, f"标题词不足({len(words)})，跳过相关性检查"

    subtitle_lower = subtitle_text.lower()
    matched = sum(1 for w in words if w in subtitle_lower)
    rate = matched / len(words) if words else 0
    reason = f"标题词{len(words)}个，命中{matched}个，匹配率{rate:.0%}"

    # 匹配率 < 20% → 判定为不相关（ASR 串台了）
    if rate < 0.20:
        return False, reason
    return True, reason


def parse_srt_char_count(srt_path: Path) -> tuple[int, str, str]:
    """读取 SRT，统计纯文字字符数（剔除序号+时间轴），返回(字数, 预览前300字, 完整纯文字)"""
    try:
        content = srt_path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        try:
            content = srt_path.read_text(encoding="utf-8")
        except UnicodeError:
            content = srt_path.read_text(encoding="gbk", errors="ignore")

    lines = [
        l.strip()
        for l in content.splitlines()
        if l.strip()
        and not l.strip().isdigit()
        and "-->" not in l
    ]
    text = " ".join(lines)
    preview = text[:300].replace("\n", " ").strip()
    return len(text), preview, text


def extract_video_title(stdout: str) -> str:
    """从 BBDown 输出中提取视频标题"""
    m = re.search(r"视频标题[:：]\s*(.+)", stdout)
    return m.group(1).strip() if m else ""


def _print(msg: str):
    """带时间戳的进度输出，用户知道当前在做什么。"""
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _validate_cookie(cookie: Optional[str]) -> tuple[bool, str]:
    """预检查 Cookie 是否有效（SESSDATA 格式）。"""
    if not cookie:
        return False, "未配置 Cookie（匿名访问可能受限）"
    if not cookie.startswith("SESSDATA="):
        return False, f"Cookie 格式异常（非 SESSDATA）：{cookie[:20]}..."
    return True, "Cookie 格式正确"


def download_subtitles(
    url: str,
    output_dir: str,
    cookie: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用 BBDown --skip-ai false 下载 AI 字幕，
    验证有效性后返回。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # ── 优化1: 缓存检查 ── 字幕已存在则跳过（仅做相关性验证，不限字数）
    _print(f"[CHECK] 检查缓存: {output_path}")
    for pattern in ["*.ai-zh.srt", "*.zh.srt", "*.srt"]:
        cached = list(output_path.glob(pattern))
        if cached:
            char_count, preview, subtitle_text = parse_srt_char_count(cached[0])
            if char_count > 0:
                # 取视频标题用于相关性验证（从文件名提取）
                video_title = cached[0].stem.split('.')[0]
                relevant, rel_reason = check_content_relevance(video_title, subtitle_text)
                if relevant:
                    _print(f"[OK] 缓存命中（{char_count} 字，相关性{rel_reason}），跳过下载")
                    return {
                        "success": True,
                        "subtitle_file": str(cached[0]),
                        "video_title": video_title,
                        "char_count": char_count,
                        "content_preview": preview[:300],
                        "message": f"使用缓存字幕，共 {char_count} 字",
                    }
                else:
                    _print(f"[WARN] 缓存字幕内容不相关（{rel_reason}），重新下载")

    # ── 优化2: Cookie 预检查 ── 提前告警，避免 BBDown 慢慢失败
    cookie_ok, cookie_msg = _validate_cookie(cookie)
    _print(f"[COOKIE] {cookie_msg}")

    bbdown = find_exe("bbdown")
    ffmpeg = find_exe("ffmpeg")

    cmd = [
        bbdown, url,
        "--sub-only",
        "--skip-ai", "false",   # 下载 AI 字幕
        "--work-dir", str(output_path),
    ]
    if ffmpeg:
        cmd.extend(["--ffmpeg-path", ffmpeg])
    if cookie:
        cmd.extend(["--cookie", cookie])

    _print(f"[DOWN] 正在下载字幕（可能需要 30s~2min）...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(output_path)
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False, "error": "BBDown 执行超时",
            "subtitle_file": None, "video_title": "", "char_count": 0,
            "content_preview": "", "message": "下载超时，请重试",
        }
    except Exception as e:
        return {
            "success": False, "error": str(e),
            "subtitle_file": None, "video_title": "", "char_count": 0,
            "content_preview": "", "message": str(e),
        }

    stdout = result.stdout
    _print(f"[OK] 字幕下载完成，正在验证...")
    video_title = extract_video_title(stdout)

    # 优先选 ai-zh（中文AI字幕），找不到再选任意 .srt
    srt_files = list(output_path.glob("*.ai-zh.srt"))
    if not srt_files:
        srt_files = list(output_path.glob("*.srt"))

    if not srt_files:
        return {
            "success": False,
            "error": "未找到字幕文件",
            "subtitle_file": None,
            "video_title": video_title,
            "char_count": 0,
            "content_preview": "",
            "message": "该视频无可用字幕，请提供 SRT/ASS 文件",
        }

    # 验证字幕有效性：仅相关性限制（不限字数，短视频字幕可能很少）
    srt_file = srt_files[0]
    char_count, preview, subtitle_text = parse_srt_char_count(srt_file)

    if char_count == 0:
        return {
            "success": False,
            "error": "字幕文件为空",
            "subtitle_file": str(srt_file),
            "video_title": video_title,
            "char_count": 0,
            "content_preview": "",
            "message": "字幕文件为空，无法处理。请提供其他字幕文件。",
        }

    # 验证内容相关性（标题关键词 vs 字幕内容）
    relevant, relevance_reason = check_content_relevance(video_title, subtitle_text)
    if not relevant:
        return {
            "success": False,
            "error": f"字幕内容与视频标题不匹配（{relevance_reason}）",
            "subtitle_file": str(srt_file),
            "video_title": video_title,
            "char_count": char_count,
            "content_preview": preview,
            "message": (
                "B站 AI 字幕内容与视频标题不相关（ASR 串台了）。"
                "请提供其他视频，或手动上传 SRT/ASS 字幕文件。"
            ),
        }

    return {
        "success": True,
        "subtitle_file": str(srt_file),
        "video_title": video_title,
        "char_count": char_count,
        "content_preview": preview,
        "message": f"字幕有效，共 {char_count} 字（{relevance_reason}）",
    }


def get_page_list(url: str, cookie: Optional[str] = None) -> list[dict]:
    """
    使用 BBDown --only-show-info 获取视频分P列表。
    返回 list of {p: int, bvid: str, title: str, url: str}
    如果是单P视频，返回列表只有一项。
    """
    bbdown = find_exe("bbdown")
    if not bbdown:
        return []

    cmd = [bbdown, url, "--only-show-info"]
    if cookie:
        cmd.extend(["--cookie", cookie])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        stdout = r.stdout
    except Exception:
        return []

    # 提取主标题
    main_title_m = re.search(r"视频标题[:：]\s*(.+)", stdout)
    main_title = main_title_m.group(1).strip() if main_title_m else ""

    # 检测分P信息（BBDown 输出格式：P1: xxx, P2: xxx...）
    pages = re.findall(r"P(\d+)[：:]\s*(.+)", stdout)

    # 提取 BV 号
    bv_match = re.search(r"(BV[A-Za-z0-9]+)", url, re.IGNORECASE)
    bv = bv_match.group(1) if bv_match else "BVunknown"

    if not pages:
        # 单P视频
        return [{"p": 1, "bvid": bv, "title": main_title or bv, "url": url}]

    result = []
    for p_num_str, p_title in pages:
        p_num = int(p_num_str)
        # 多P URL 格式：https://www.bilibili.com/video/BVxxx/?p=N
        if "bilibili.com" in url:
            base_url = re.sub(r'[?&]p=\d+', '', url).rstrip('/')
            p_url = f"{base_url}?p={p_num}"
        else:
            p_url = f"https://www.bilibili.com/video/{bv}/?p={p_num}"
        result.append({
            "p": p_num,
            "bvid": bv,
            "title": p_title.strip(),
            "url": p_url,
        })
    return result


def download_multi_p(
    url: str,
    base_dir: str,
    cookie: Optional[str] = None,
    video_only_on_fail: bool = True,
) -> Dict[str, Any]:
    """
    下载多P视频：每个分P下载到独立子目录。
    子目录命名：p{N:02d}_{分P标题（sanitize后）}

    video_only_on_fail=True 时：字幕无效的分P仍下载视频（不走后续 pipeline）。

    返回：
    {
      "total": N,
      "pages": [
        {
          "p": 1,
          "title": "xxx",
          "task_dir": "/path/...",
          "subtitle_result": {...},  # download_subtitles 返回值
          "video_only": bool,        # True = 仅下载视频，不走 pipeline
        },
        ...
      ]
    }
    """
    _print(f"[INFO] 获取分P列表...")
    pages = get_page_list(url, cookie)
    _print(f"[INFO] 共 {len(pages)} P")

    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    results = []
    for page in pages:
        p_num = page["p"]
        p_title = page["title"]
        p_url = page["url"]

        # 子目录：p01_标题
        sub_name = f"p{p_num:02d}_{sanitize_dirname(p_title, max_len=40)}"
        sub_dir = base_path / sub_name
        sub_dir.mkdir(parents=True, exist_ok=True)

        _print(f"[P{p_num}] 正在处理：{p_title}")
        sub_result = download_subtitles(p_url, str(sub_dir), cookie)

        video_only = not sub_result["success"]
        if video_only and video_only_on_fail:
            _print(f"[P{p_num}] 字幕无效（{sub_result.get('message','')}），仅下载视频...")
            _download_video_only(p_url, str(sub_dir), cookie)

        results.append({
            "p": p_num,
            "title": p_title,
            "task_dir": str(sub_dir.resolve()),
            "subtitle_result": sub_result,
            "video_only": video_only,
        })

    return {
        "total": len(pages),
        "pages": results,
    }


def _download_video_only(url: str, output_dir: str, cookie: Optional[str] = None) -> bool:
    """
    仅下载视频文件（不走字幕/pipeline），用于无字幕分P。
    """
    bbdown = find_exe("bbdown")
    ffmpeg = find_exe("ffmpeg")
    if not bbdown:
        _print("[ERROR] BBDown 未找到，无法下载视频")
        return False

    cmd = [bbdown, url, "--work-dir", output_dir]
    if ffmpeg:
        cmd.extend(["--ffmpeg-path", str(ffmpeg)])
    if cookie:
        cmd.extend(["--cookie", cookie])

    _print(f"[DOWN] 下载视频到 {output_dir}...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=output_dir)
        return r.returncode == 0
    except Exception as e:
        _print(f"[ERROR] 视频下载失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="下载B站视频CC字幕（bilibili-gameguide 版）")
    parser.add_argument("--url", required=True, help="B站视频URL或BV号")
    parser.add_argument("--output", default=None,
                        help="直接指定输出目录（legacy 模式，与 --make-dir 互斥）")
    parser.add_argument("--cookie", default=None, help="B站 SESSDATA cookie（可选）")
    parser.add_argument(
        "--make-dir", default=None,
        metavar="BASE_DIR",
        nargs="?",
        const="",   # 传 --make-dir 但不带值时 = 使用配置根目录
        help="在 base_dir 下按规范命名创建任务目录（BV号_视频名_任务时间）。"
             "省略值或传 'auto' 时使用设备配置的下载根目录（首次使用会引导设置）。"
    )
    parser.add_argument(
        "--show-download-root", action="store_true",
        help="显示当前设备配置的下载根目录"
    )

    args = parser.parse_args()

    # --show-download-root: 仅显示配置
    if args.show_download_root:
        root = get_download_root()
        if root:
            print(f"[OK] 下载根目录：{root}")
        else:
            print("[未配置] 运行以下命令设置：")
            print("  python check_dependencies.py --set-download-root <路径>")
        sys.exit(0)

    # legacy 模式：显式传了 --output 且没传 --make-dir
    if args.output is not None and args.make_dir is None:
        result = download_subtitles(args.url, str(args.output), args.cookie)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["success"] else 1)

    # make-dir 模式（默认行为）
    # base_dir: None 或 '' 或 'auto' → 使用配置根目录；否则使用指定目录
    base_dir_arg: Optional[str] = None
    if args.make_dir and args.make_dir.lower() not in ("", "auto"):
        base_dir_arg = args.make_dir

    # 提取 BV 号
    bv_match = re.search(r'(BV[A-Za-z0-9]+)', args.url, re.IGNORECASE)
    bv = bv_match.group(1) if bv_match else 'BVunknown'

    # 先下载到临时目录获取标题，再建最终目录
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        r = download_subtitles(args.url, tmp, args.cookie)
        video_title = r.get("video_title") or bv
        # make_task_dir 内部会处理 base_dir=None → 读取配置根目录 → 首次引导设置
        final_dir = make_task_dir(base_dir_arg, bv, video_title)
        # 将临时目录内容移动到最终目录
        for item in Path(tmp).iterdir():
            dest = Path(final_dir) / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))
        # 修正 subtitle_file 路径
        if r.get("subtitle_file"):
            old_p = Path(r["subtitle_file"])
            new_p = Path(final_dir) / old_p.name
            r["subtitle_file"] = str(new_p) if new_p.exists() else r["subtitle_file"]
        r["task_dir"] = final_dir
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["success"] else 1)


if __name__ == "__main__":
    main()
