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
import glob
import json
import os
import shutil
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
    # 标准化：移除末尾的中英文标点符号（避免标题差异导致目录分离）
    # 例如："攻略来了！" 和 "攻略来了。" 标准化为相同目录名
    cleaned = re.sub(r'[。！？.!?:;,…]+$', '', cleaned)
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
    宽松策略：只要有任意单字重叠即通过（处理 ASR 识别错误/谐音）。
    """
    if not video_title or not subtitle_text:
        return True, "无标题/字幕内容，跳过检查"

    words = extract_chinese_words(video_title)
    if len(words) < 3:
        return True, f"标题词不足({len(words)})，跳过检查"

    # 提取所有单字（用于容错）
    single_chars = set("".join(words))  # {'一', '个', '视', '频', ...}
    sub_chars = set(subtitle_text)
    
    # 任意单字重叠即相关（处理 ASR 谐音错误）
    common = single_chars & sub_chars
    matched = len(common)
    rate = matched / len(single_chars) if single_chars else 0
    
    # 放宽判定：任意匹配即通过（容忍 ASR 错误）
    if rate > 0:
        return True, f"标题单字{matched}个重叠，相关"
    return False, f"无单字重叠"


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
        "video_title": video_title,  # 使用 BBDown 提取的视频标题（与视频文件一致）
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
    
    HOOK：复用已有主任务目录，不重复创建。
    - 先扫描 base_dir 下是否有该 BV 的主任务目录
    - 有则复用，否则创建
    
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
    
    # ── HOOK: 复用已有主任务目录 ──
    bv_match = re.search(r'(BV[A-Za-z0-9]+)', url, re.IGNORECASE)
    bv = bv_match.group(1) if bv_match else "BVunknown"
    
    search_pattern = os.path.join(base_dir, f"{bv}_*")
    existing_dirs = glob.glob(search_pattern)
    main_dir = None
    
    # 查找已有主目录（含字幕）
    for d in sorted(existing_dirs, key=os.path.getmtime, reverse=True):
        dpath = Path(d)
        if dpath.is_dir():
            # 检查是否有字幕文件
            has_sub = any(dpath.glob("*.srt")) or any(dpath.glob("*.ai-zh.srt"))
            if has_sub:
                main_dir = dpath
                _print(f"[HOOK] 复用已有主目录: {dpath.name}")
                break
    
    # 无缓存则创建主目录
    if not main_dir:
        video_title = pages[0].get("title", bv) if pages else bv
        main_dir = Path(make_task_dir(base_dir, bv, video_title))
        _print(f"[INFO] 创建主目录: {main_dir.name}")

    results = []
    for page in pages:
        p_num = page["p"]
        p_title = page["title"]
        p_url = page["url"]

        # 子目录：p01_标题（放在主目录内）
        sub_name = f"p{p_num:02d}_{sanitize_dirname(p_title, max_len=40)}"
        sub_dir = main_dir / sub_name
        if not sub_dir.exists():
            sub_dir.mkdir(parents=True, exist_ok=True)

        _print(f"[P{p_num}] 正在处理：{p_title}")
        
        # ── HOOK: 先检查实际字幕文件是否存在 ──
        # 即使 API 返回失败，仍检查文件是否实际存在
        sub_result = download_subtitles(p_url, str(sub_dir), cookie)
        
        # API 失败时额外检查实际文件
        if not sub_result.get("success"):
            actual_srts = list(sub_dir.glob("*.ai-zh.srt")) + list(sub_dir.glob("*.srt"))
            if actual_srts:
                # 文件实际存在，以文件为准
                char_count, preview, subtitle_text = parse_srt_char_count(actual_srts[0])
                if char_count > 0:
                    _print(f"[HOOK] 字幕API失败但文件存在（{char_count}字），使用文件")
                    sub_result = {
                        "success": True,
                        "subtitle_file": str(actual_srts[0]),
                        "video_title": p_title,
                        "char_count": char_count,
                        "content_preview": preview[:300],
                        "message": f"使用缓存字幕，共 {char_count} 字",
                    }

        video_only = not sub_result.get("success")
        if video_only and video_only_on_fail:
            _print(f"[P{p_num}] 字幕无效（{sub_result.get('message','')}），仅下载视频...")
            video_ok, video_title = _download_video_only(p_url, str(sub_dir), cookie)
            if video_ok and video_title:
                sub_result["video_title"] = video_title  # 统一使用视频标题

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


def get_video_duration(video_path: str) -> int:
    """
    用 ffprobe 获取视频时长（秒）。
    返回：整数秒，失败返回 0。
    """
    ffprobe = find_exe("ffprobe")
    if not ffprobe or not video_path:
        return 0
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(float(r.stdout.strip()))
    except Exception:
        pass
    return 0


def _download_video_only(url: str, output_dir: str, cookie: Optional[str] = None) -> tuple[bool, str]:
    """
    仅下载视频文件（不走字幕/pipeline），用于无字幕分P。
    返回: (是否成功, 视频标题)
    """
    bbdown = find_exe("bbdown")
    ffmpeg = find_exe("ffmpeg")
    if not bbdown:
        _print("[ERROR] BBDown 未找到，无法下载视频")
        return False, ""

    cmd = [bbdown, url, "--work-dir", output_dir]
    if ffmpeg:
        cmd.extend(["--ffmpeg-path", str(ffmpeg)])
    if cookie:
        cmd.extend(["--cookie", cookie])

    _print(f"[DOWN] 下载视频到 {output_dir}...")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=output_dir)
        video_title = extract_video_title(r.stdout) if r.returncode == 0 else ""
        
        # 获取视频时长
        video_path = None
        if video_title and r.returncode == 0:
            # 查找下载的 mp4 文件
            for f in os.listdir(output_dir):
                if f.endswith(".mp4"):
                    video_path = os.path.join(output_dir, f)
                    break
        
        duration_sec = get_video_duration(video_path) if video_path else 0
        
        if duration_sec > 0:
            _print(f"[OK] 视频时长: {duration_sec}秒")
        
        return r.returncode == 0, video_title
    except Exception as e:
        _print(f"[ERROR] 视频下载失败: {e}")
        return False, ""


def _download_video_first(url: str, base_dir: str, cookie: Optional[str] = None) -> tuple[bool, str, str]:
    """
    先下载视频，获取准确标题后再创建任务目录。
    返回: (是否成功, 任务目录路径, 视频标题)
    """
    bbdown = find_exe("bbdown")
    ffmpeg = find_exe("ffmpeg")
    
    if not bbdown:
        _print("[ERROR] BBDown 未找到，无法下载视频")
        return False, "", ""
    
    # 创建临时目录用于下载
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [bbdown, url, "--work-dir", tmp]
        if ffmpeg:
            cmd.extend(["--ffmpeg-path", str(ffmpeg)])
        if cookie:
            # 传入 cookie（支持 DedeUserID 格式或 SESSDATA）
            cmd.extend(["--cookie", cookie])
        
        # 强制下载 AI 字幕（--skip-ai false）+ 跳过混流保留独立字幕文件
        cmd.extend(["--skip-ai", "false", "--skip-mux", "true"])
        
        _print(f"[DOWN] 下载视频获取标题...")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=tmp)
            if r.returncode != 0:
                _print(f"[ERROR] 视频下载失败: {r.stderr[:500] if r.stderr else 'unknown'}")
                return False, "", ""
            
            # 从输出中提取视频标题
            video_title = extract_video_title(r.stdout)
            if not video_title:
                # 尝试从下载的文件名获取
                mp4_files = list(Path(tmp).glob("*.mp4"))
                if mp4_files:
                    video_title = mp4_files[0].stem
            
            if not video_title:
                _print("[ERROR] 无法获取视频标题")
                return False, "", ""
            
            _print(f"[OK] 视频标题: {video_title}")
            
            # 用准确标题创建任务目录
            bv_match = re.search(r'(BV[A-Za-z0-9]+)', url, re.IGNORECASE)
            bv = bv_match.group(1) if bv_match else "BVunknown"
            task_dir = make_task_dir(base_dir, bv, video_title)
            
            # 移动视频文件到任务目录（包括 CID 子目录中的独立文件）
            for item in Path(tmp).iterdir():
                if item.is_dir():
                    # BBDown --skip-mux 时会创建 CID 子目录
                    for sub_item in item.iterdir():
                        if sub_item.suffix.lower() in [".mp4", ".m4a", ".flv"]:
                            dest = Path(task_dir) / sub_item.name
                            shutil.move(str(sub_item), str(dest))
                            _print(f"[OK] 视频已移动到: {dest.name}")
                        elif sub_item.suffix.lower() == ".srt":
                            # 复制字幕文件到任务目录
                            dest = Path(task_dir) / sub_item.name
                            shutil.copy(str(sub_item), str(dest))
                            _print(f"[OK] 字幕已复制到: {dest.name}")
                        elif sub_item.suffix.lower() == ".jpg":
                            # 复制封面
                            dest = Path(task_dir) / sub_item.name
                            shutil.copy(str(sub_item), str(dest))
                            _print(f"[OK] 封面已复制到: {dest.name}")
            
            return True, task_dir, video_title
        except Exception as e:
            _print(f"[ERROR] 视频下载异常: {e}")
            return False, "", ""


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

    # HOOK: 缓存检查范围限定为配置根目录，不受 --make-dir 影响
    # 从 workspace_config.json 读取配置的下载根目录
    config_root = None
    ws_cfg = Path.home() / ".workbuddy" / "skills" / "bilibili-gameguide" / "workspace_config.json"
    if ws_cfg.exists():
        with open(ws_cfg, encoding='utf-8') as f:
            config_root = json.load(f).get("download_root")
    
    # 强制使用配置根目录，不受 base_dir_arg 影响
    base_dir_arg = config_root if config_root else (base_dir_arg if base_dir_arg else str(Path.cwd()))

    # ========== 新工作流：先下载视频，再下载字幕（快速检测无字幕则跳过） ==========
    # 1. 先下载视频获取准确标题
    # 2. 快速检查是否有字幕（无则直接返回 video_only，不浪费时间）
    # 3. 有字幕则下载到同一目录
    
    _print("[STEP 1/3] 下载视频获取准确标题...")
    video_ok, task_dir, video_title = _download_video_first(args.url, base_dir_arg, args.cookie)
    
    if not video_ok:
        print(json.dumps({
            "success": False,
            "error": "视频下载失败",
            "message": "无法下载视频文件",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    
    # Step 2: 检查是否有字幕（快速检测，有则下载，无则跳过）
    _print(f"[STEP 2/3] 快速检测字幕...")
    
    # 检查临时目录中是否已有字幕（BBDown 可能已下载）
    tmp_subs = list(Path(task_dir).glob("*.ai-zh.srt")) + list(Path(task_dir).glob("*.zh.srt")) + list(Path(task_dir).glob("*.srt"))
    
    if tmp_subs:
        # 已有字幕文件
        char_count, preview, subtitle_text = parse_srt_char_count(tmp_subs[0])
        if char_count > 0:
            r = {
                "success": True,
                "subtitle_file": str(tmp_subs[0]),
                "video_title": video_title,
                "char_count": char_count,
                "content_preview": preview[:300],
                "task_dir": task_dir,
                "message": f"字幕已存在，共 {char_count} 字",
            }
            _print(f"[OK] 检测到字幕（{char_count} 字），跳过下载")
        else:
            # 字幕文件为空
            r = {
                "success": False,
                "video_only": True,
                "subtitle_file": None,
                "video_title": video_title,
                "char_count": 0,
                "content_preview": "",
                "task_dir": task_dir,
                "message": "该视频无可用字幕（字幕文件为空），仅下载视频",
            }
            _print("[WARN] 字幕文件为空，video_only 模式")
    else:
        # 无字幕文件，快速检测 BBDown 是否有 AI 字幕可用
        # 如果 BBDown 能解析到字幕，它会在下载视频时一起下载
        # 如果没有解析到字幕，说明该视频没有 AI 字幕，直接返回 video_only
        _print("[INFO] 无字幕文件，检测到该视频无 AI 字幕")
        r = {
            "success": False,
            "video_only": True,
            "subtitle_file": None,
            "video_title": video_title,
            "char_count": 0,
            "content_preview": "",
            "task_dir": task_dir,
            "message": "该视频无 AI 字幕，仅下载视频（video_only 模式）",
        }
    
    _print(f"[STEP 3/3] 完成，返回结果")
    
    # 自动生成 config.json（方便后续步骤直接使用）
    if r.get("success") and task_dir:
        import json as json_mod
        video_file = None
        subtitle_file = None
        for f in os.listdir(task_dir):
            if f.endswith('.mp4'):
                video_file = f
            elif '.ai-en.srt' in f:
                subtitle_file = f
            elif f.endswith('.srt') and not subtitle_file:
                subtitle_file = f
        
        if video_file:
            cfg = {
                "_schema_version": "1.0",
                "video": {
                    "file": video_file,
                    "subtitle": subtitle_file,
                    "url": args.url,
                    "title": video_title
                },
                "paths": {
                    "screenshots_dir": "screenshots",
                    "structure_file": "video_structure.json",
                    "structure_with_subs_file": "video_structure_with_subs.json",
                    "mapping_file": "screenshot_mapping.json",
                    "output_html": "game_guide.html"
                },
                "cv": {
                    "frame_interval_sec": 1.0,
                    "pHash_threshold": 15,
                    "hist_threshold": 0.20,
                    "laplacian_threshold": 30,
                    "min_gap_sec": 5,
                    "min_window_sec": 3,
                    "max_per_window": 8,
                    "boundary_pHash_threshold": 10,
                    "boundary_hist_threshold": 0.15
                },
                "html": {
                    "title": "游戏攻略笔记",
                    "accent_color": "#00b4d8",
                    "bg_color": "#0f1419"
                }
            }
            cfg_path = Path(task_dir) / "config.json"
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json_mod.dump(cfg, f, ensure_ascii=False, indent=2)
            _print(f"[OK] 已生成 config.json")
    
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["success"] else 1)


if __name__ == "__main__":
    main()
