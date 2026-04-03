"""
=====================================================================
B站视频游戏攻略 · Step 3：生成最终 HTML
=====================================================================
从 config.json 读取配置和 CSS 主题参数。
从 video_structure.json 读取语义结构（concise_summary + bullet_points）。
从 screenshot_mapping.json 读取截图归属。
组装最终 HTML：视频信息面板 + 固定目录导航 + 多级标题 + 摘要 + 截图。

输出一个纯静态 HTML 文件（无外部依赖），直接可分享。

用法：
    python step3_generate_html.py [config_path]
    # 默认读取同目录下的 config.json
=====================================================================
"""

import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"

REASON_LABELS = {
    "first":  "首帧",
    "last":   "末帧",
    "sample": "采样",
}


# ------------------------------------------------------------------ #
# 配置 & 时间工具                                                    #
# ------------------------------------------------------------------ #

def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sec_to_ts(s: float | int) -> str:
    s = max(0, int(s))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


# ------------------------------------------------------------------ #
# 标题工具                                                          #
# ------------------------------------------------------------------ #

def strip_heading_prefix(h: str) -> str:
    return h.lstrip("# ").strip()


def make_anchor_id(text: str) -> str:
    s = strip_heading_prefix(text)
    s = re.sub(r"[^\w\u4e00-\u9fff]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:60] or "section"


# ------------------------------------------------------------------ #
# CSS 构建（参数全部来自 config.json，无硬编码）                      #
# ------------------------------------------------------------------ #

def build_css(cfg: dict) -> str:
    html = cfg.get("html", {})
    accent   = html.get("accent_color",   "#00b4d8")
    bg       = html.get("bg_color",       "#0f1419")
    card     = html.get("card_color",     "#1c2128")
    text     = html.get("text_color",     "#e6edf3")
    border   = html.get("border_color",   "#30363d")
    tag      = html.get("tag_color",      "#58a6ff")
    font     = html.get("font_family",     "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif")
    max_w    = html.get("max_width",      "860px")
    toc_bg   = html.get("toc_bg_color",   "#0d1117")
    toc_w    = html.get("toc_width",      "260px")

    return f"""  :root {{
    --accent: {accent};
    --bg:     {bg};
    --card:   {card};
    --text:   {text};
    --border: {border};
    --tag:    {tag};
    --toc-w:  {toc_w};
    --toc-bg: {toc_bg};
    --max-w:  {max_w};
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html {{ scroll-behavior: smooth; }}

  .layout {{
    display: flex; align-items: flex-start;
    max-width: 1400px; margin: 0 auto;
    padding: 1rem; gap: 1.5rem;
  }}

  .toc-sidebar {{
    width: var(--toc-w); min-width: var(--toc-w);
    max-height: 100vh; position: sticky; top: 1rem;
    overflow-y: auto; background: var(--toc-bg);
    border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem; flex-shrink: 0;
    scrollbar-width: thin; scrollbar-color: var(--border) transparent;
  }}
  .toc-sidebar::-webkit-scrollbar {{ width: 4px; }}
  .toc-sidebar::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
  .toc-title {{
    font-size: .8rem; font-weight: 700; color: var(--accent);
    letter-spacing: .08em; text-transform: uppercase;
    margin-bottom: .8rem; padding-bottom: .5rem;
    border-bottom: 1px solid var(--border);
  }}
  .toc-list {{ list-style: none; }}
  .toc-h2 {{ margin: .4rem 0 .2rem; }}
  .toc-h3 {{ margin: .1rem 0 .1rem .8rem; }}
  .toc-link {{
    display: block; font-size: .82rem; color: #8b949e;
    text-decoration: none; padding: .2rem .4rem; border-radius: 4px;
    transition: color .15s, background .15s;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .toc-link:hover {{ color: var(--text); background: var(--card); }}
  .toc-link.sub {{ font-size: .76rem; }}

  .main {{ flex: 1; min-width: 0; max-width: var(--max-w); }}

  .video-banner {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.4rem 1.6rem; margin-bottom: 2rem;
  }}
  .banner-title {{
    display: flex; align-items: flex-start;
    justify-content: space-between; gap: 1rem;
    margin-bottom: 1rem; flex-wrap: wrap;
  }}
  .banner-title h1 {{ font-size: 1.5rem; font-weight: 700; color: var(--text); line-height: 1.3; }}
  .btn-link {{
    display: inline-block; padding: .4rem .9rem;
    background: var(--accent); color: #fff;
    border-radius: 6px; text-decoration: none;
    font-size: .85rem; white-space: nowrap; transition: opacity .2s;
  }}
  .btn-link:hover {{ opacity: .85; text-decoration: none; }}
  .meta-grid {{ display: flex; flex-wrap: wrap; gap: .4rem 1.5rem; margin-bottom: .8rem; }}
  .meta-item {{ display: flex; align-items: center; gap: .4rem; font-size: .82rem; }}
  .meta-label {{
    color: #8b949e; background: var(--bg);
    padding: .15rem .5rem; border-radius: 4px;
    border: 1px solid var(--border); white-space: nowrap;
  }}
  .meta-value {{ color: var(--text); }}
  .video-desc {{
    font-size: .82rem; color: #8b949e; line-height: 1.7;
    margin-top: .5rem; padding: .6rem 1rem;
    background: var(--bg); border-left: 3px solid var(--accent);
  }}

  body {{ font-family: {font}; background: var(--bg); color: var(--text); line-height: 1.8; padding: 1rem 0; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 1rem; color: var(--accent); }}
  h2 {{ font-size: 1.3rem; margin: 2.2rem 0 1rem; padding-bottom: .5rem; border-bottom: 2px solid var(--border); color: var(--accent); }}
  h3 {{ font-size: 1.05rem; margin: 1.4rem 0 .6rem; color: var(--tag); }}
  h4 {{ font-size: .95rem; margin: .8rem 0 .3rem; color: var(--text); opacity: .85; }}
  p  {{ margin: .65rem 0; font-size: .95rem; }}
  blockquote {{ margin: 1rem 0; padding: .8rem 1rem; background: var(--card); border-left: 4px solid var(--accent); border-radius: 0 6px 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .9rem; }}
  th, td {{ padding: .5rem .8rem; border: 1px solid var(--border); }}
  th {{ background: var(--card); color: var(--accent); }}
  ul, ol {{ margin: .5rem 0 .5rem 1.5rem; }}
  li {{ margin: .3rem 0; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}
  code {{ background: var(--card); padding: .1rem .3rem; border-radius: 3px; font-size: .9em; }}

  .summary-text {{
    margin: .8rem 0; font-size: .95rem; line-height: 1.85; color: var(--text);
    padding: .7rem 1rem; background: var(--card);
    border-left: 3px solid var(--accent); border-radius: 0 6px 6px 0;
  }}
  .summary-bullets {{
    list-style: none; margin: .6rem 0 1rem 0; padding: 0;
    display: flex; flex-wrap: wrap; gap: .4rem;
  }}
  .summary-bullets li {{
    background: var(--card); border: 1px solid var(--border);
    border-left: 3px solid var(--tag); border-radius: 4px;
    padding: .3rem .75rem; font-size: .84rem; color: var(--text); margin: 0;
  }}

  .ts-range {{ font-size: .72rem; color: #8b949e; font-weight: normal; margin-left: .5rem; font-family: monospace; }}

  figure.screenshot {{ margin: 1.5rem 0; text-align: center; }}
  figure.screenshot img {{
    max-width: 100%; border-radius: 8px; border: 1px solid var(--border);
    display: block; margin: 0 auto; transition: box-shadow .2s;
  }}
  figure.screenshot img:hover {{ box-shadow: 0 4px 20px rgba(0,180,216,.2); }}
  figcaption {{ font-size: .78rem; color: #8b949e; margin-top: .4rem; }}
  .shot-hint {{ font-size: .74rem; color: #6e7681; margin-top: .2rem; font-style: italic; }}

  @media (max-width: 768px) {{ .layout {{ flex-direction: column; padding: .5rem; }} .toc-sidebar {{ display: none; }} }}"""


# ------------------------------------------------------------------ #
# HTML 各部分构建                                                    #
# ------------------------------------------------------------------ #

def _resolve_heading(section: dict) -> str:
    """从 section 字典中取标题，优先 heading > title > id。"""
    return section.get("heading") or section.get("title") or str(section.get("id", ""))


def build_toc(structure: dict) -> str:
    """构建左侧目录导航 HTML，兼容 heading / title 两种字段名。"""
    items = []
    for section in structure.get("sections", []):
        h = _resolve_heading(section)
        sid  = make_anchor_id(h)
        name = strip_heading_prefix(h)
        items.append(f'<li class="toc-h2"><a href="#{sid}" class="toc-link">{name}</a></li>')
        for sub in section.get("subsections", []):
            sub_h = _resolve_heading(sub)
            sub_sid  = make_anchor_id(sub_h)
            sub_name = strip_heading_prefix(sub_h)
            items.append(f'<li class="toc-h3"><a href="#{sub_sid}" class="toc-link sub">{sub_name}</a></li>')
    return "\n".join(items)


def build_video_info(video_cfg: dict, concise_summary: str = "") -> str:
    title    = video_cfg.get("title", "视频笔记")
    url      = video_cfg.get("url", "#")
    bv_id    = video_cfg.get("bv_id", "")
    uploader = video_cfg.get("uploader", "未知")
    pub_date = video_cfg.get("publish_date", "")
    duration = video_cfg.get("duration_sec", 0)
    view_cnt = video_cfg.get("view_count", "")
    danmu    = video_cfg.get("danmu_count", "")
    likes    = video_cfg.get("likes", "")
    coins    = video_cfg.get("coins", "")
    favorites= video_cfg.get("favorites", "")
    # 优先用 video.description；没有则用传入的 concise_summary
    desc     = video_cfg.get("description", "") or concise_summary

    meta_rows = []
    def add_row(label, value):
        if value:
            meta_rows.append(
                f'<div class="meta-item">'
                f'<span class="meta-label">{label}</span>'
                f'<span class="meta-value">{value}</span></div>'
            )
    add_row("BV号",     bv_id)
    add_row("UP主",     uploader)
    add_row("发布时间", pub_date)
    add_row("视频时长", sec_to_ts(duration))
    if view_cnt:   add_row("播放量", view_cnt)
    if danmu:      add_row("弹幕数", danmu)
    if likes:      add_row("点赞数", likes)
    if coins:      add_row("投币数", coins)
    if favorites:  add_row("收藏数", favorites)

    meta_html = "\n".join(meta_rows)
    desc_html = (f'<blockquote class="video-desc">{desc}</blockquote>' if desc else "")

    return "\n".join([
        '<div class="video-banner">',
        '  <div class="banner-title">',
        f'    <h1>{title}</h1>',
        '    <div class="banner-actions">',
        f'      <a href="{url}" target="_blank" class="btn-link">&#9654; 前往B站观看</a>',
        '    </div>',
        '  </div>',
        '  <div class="meta-grid">', meta_html, '  </div>',
        desc_html, '</div>',
    ])


def build_screenshot_block(shots: list[dict], shots_dir: Path, config_dir: Path) -> str:
    blocks = []
    for shot in shots:
        ts  = shot["timestamp"]
        fn  = shot["filename"]
        lbl = REASON_LABELS.get(shot.get("reason", ""), shot.get("reason", ""))
        hint = shot.get("subtitle_hint", "")
        rel_path = os.path.relpath(shots_dir / fn, config_dir).replace("\\", "/")
        hint_html = f'<p class="shot-hint">{hint}</p>' if hint else ""
        blocks.append(
            f'<figure class="screenshot">'
            f'<img src="{rel_path}" alt="截图 {sec_to_ts(ts)}" loading="lazy">'
            f'<figcaption>[{sec_to_ts(ts)}] {lbl}</figcaption>'
            f'{hint_html}</figure>'
        )
    return "\n".join(blocks)


def build_summary_block(concise_summary: str, bullet_points: list) -> str:
    parts = []
    if concise_summary:
        parts.append(f"<p class='summary-text'>{concise_summary.strip()}</p>")
    if bullet_points:
        items = "\n".join(
            f"<li>{bp.strip()}</li>" for bp in bullet_points if bp.strip()
        )
        if items:
            parts.append(f"<ul class='summary-bullets'>{items}</ul>")
    return "\n".join(parts)


def subtitles_to_text(subtitles: list, max_lines: int = 20) -> str:
    """将字幕数组转为自然段落文字，用于章节正文内容。

    兼容两种格式：
    - step1_parse_srt.py 输出：[{"start": int, "end": int, "text": str}, ...]
    - LLM 直接生成：["字幕内容1", "字幕内容2", ...]（字符串数组）
    """
    if not subtitles:
        return ""
    # 兼容字符串数组 vs 对象数组
    if isinstance(subtitles[0], str):
        texts = [t.strip() for t in subtitles if t.strip()]
    else:
        texts = [s["text"].strip() for s in subtitles if s.get("text", "").strip()]
    if not texts:
        return ""
    # 合并，去掉连续重复
    merged = []
    for t in texts:
        if not merged or t != merged[-1]:
            merged.append(t)
    # 截断
    if len(merged) > max_lines:
        merged = merged[:max_lines]
    paragraph = "".join(t + "。" if not t.endswith(("。", "！", "？", ".", "!", "?")) else t for t in merged)
    return paragraph


def build_section(section: dict, sub_shots: dict,
                  shots_dir: Path, config_dir: Path) -> str:
    parts = []
    h     = _resolve_heading(section)
    level = section.get("level", 2)
    tag   = "h2" if level == 2 else "h3"
    sid   = make_anchor_id(h)
    name  = strip_heading_prefix(h)
    ts_range = f"[{sec_to_ts(section['start_sec'])}\u2013{sec_to_ts(section['end_sec'])}]"

    parts.append(f'<{tag} id="{sid}">{name} <span class="ts-range">{ts_range}</span></{tag}>')

    # 优先用 concise_summary/bullet_points；没有则用 subtitles 转为正文
    concise = section.get("concise_summary", "")
    bullets = section.get("bullet_points", [])
    subtitles = section.get("subtitles", [])

    summary_html = build_summary_block(concise, bullets)
    if not summary_html and subtitles:
        # subtitles 直接作为正文段落（不加 summary-text 样式，用普通 p 标签）
        body_text = subtitles_to_text(subtitles)
        if body_text:
            parts.append(f"<p>{body_text}</p>")
    elif summary_html:
        parts.append(summary_html)

    for sub in section.get("subsections", []):
        sub_tag  = "h3" if sub.get("level", 3) == 3 else "h4"
        sub_h    = _resolve_heading(sub)
        sub_sid  = make_anchor_id(sub_h)
        sub_name = strip_heading_prefix(sub_h)
        sub_range = f"[{sec_to_ts(sub['start_sec'])}\u2013{sec_to_ts(sub['end_sec'])}]"
        parts.append(f'<{sub_tag} id="{sub_sid}">{sub_name} <span class="ts-range">{sub_range}</span></{sub_tag}>')

        sub_summary_html = build_summary_block(
            sub.get("concise_summary", ""), sub.get("bullet_points", [])
        )
        sub_subtitles = sub.get("subtitles", [])
        if not sub_summary_html and sub_subtitles:
            body_text = subtitles_to_text(sub_subtitles)
            if body_text:
                parts.append(f"<p>{body_text}</p>")
        elif sub_summary_html:
            parts.append(sub_summary_html)

        shot_key = strip_heading_prefix(sub_h)
        shots = sub_shots.get(shot_key, [])
        if shots:
            parts.append(build_screenshot_block(shots, shots_dir, config_dir))

    if not section.get("subsections"):
        shot_key = strip_heading_prefix(h)
        shots = sub_shots.get(shot_key, [])
        if shots:
            parts.append(build_screenshot_block(shots, shots_dir, config_dir))

    return "\n".join(parts)


def build_body(structure: dict, sub_shots: dict,
               shots_dir: Path, config_dir: Path) -> str:
    parts = [build_section(s, sub_shots, shots_dir, config_dir)
             for s in structure.get("sections", [])]
    return "\n<hr>\n".join(parts)


def build_html(cfg: dict, config_dir: Path,
               structure: dict, mapping: list[dict],
               shots_dir: Path) -> str:
    html_cfg   = cfg.get("html", {})
    video_cfg  = cfg.get("video", {})
    page_title = html_cfg.get("title", "游戏攻略笔记")

    # 构建 id → heading 映射（兼容新旧两种格式）
    id_to_title = {}
    for sec in structure.get("sections", []):
        sid = sec["id"]
        # 优先用 title 字段（新格式），没有则用 heading 去掉 # 前缀（旧格式）
        if "title" in sec:
            id_to_title[sid] = sec["title"]
        elif "heading" in sec:
            id_to_title[sid] = strip_heading_prefix(sec["heading"])
        # id 可能是 int（step2 新格式）或 str（旧格式），两边都注册
        try:
            id_to_title[int(sid)] = id_to_title[sid]
        except (ValueError, TypeError):
            pass

    def resolve_subsection(raw):
        if isinstance(raw, int):
            # step2 新格式：subsection 为 int（section id），转换为标题
            return id_to_title.get(raw, str(raw))
        # 旧格式：subsection 为字符串 "### 标题" 或已经是纯标题
        return strip_heading_prefix(str(raw))

    sub_shots = {
        resolve_subsection(item["subsection"]): item["screenshots"]
        for item in mapping
    }

    return "\n".join([
        "<!DOCTYPE html>",
        "<html lang=\"zh-CN\">",
        "<head>",
        "<meta charset=\"UTF-8\">",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
        f"<title>{page_title}</title>",
        "<style>", build_css(cfg), "</style>",
        "</head>",
        "<body>",
        '<div class="layout">',
        '  <nav class="toc-sidebar" aria-label="目录导航">',
        '    <div class="toc-title">&#9776; 目录</div>',
        "    <ul class=\"toc-list\">", build_toc(structure),
        "    </ul>",
        "  </nav>",
        "  <main class=\"main\">",
        build_video_info(video_cfg, concise_summary=structure.get("concise_summary", "")),
        build_body(structure, sub_shots, shots_dir, config_dir),
        "  </main>",
        "</div>",
        "</body>",
        "</html>",
    ])


# ------------------------------------------------------------------ #
# 主逻辑                                                            #
# ------------------------------------------------------------------ #

def run(config_path: str | Path | None = None):
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    cfg = load_config(config_path)
    config_dir = config_path.parent.resolve()
    paths_cfg  = cfg["paths"]

    struct_path  = config_dir / paths_cfg.get("structure_with_subs_file", "video_structure.json")
    mapping_path = config_dir / paths_cfg.get("mapping_file", "screenshot_mapping.json")

    if not struct_path.exists():
        raise FileNotFoundError(f"语义结构文件不存在: {struct_path}，请先运行 step1 和 step2。")
    if not mapping_path.exists():
        raise FileNotFoundError(f"截图映射文件不存在: {mapping_path}，请先运行 step2。")

    with open(struct_path, encoding="utf-8") as f:
        structure = json.load(f)
    with open(mapping_path, encoding="utf-8") as f:
        mapping = json.load(f)

    shots_dir = config_dir / paths_cfg["screenshots_dir"]
    html_out  = config_dir / paths_cfg.get("output_html", "game_guide.html")

    html = build_html(cfg, config_dir, structure, mapping, shots_dir)
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(html_out) / 1024
    print(f"HTML 生成完成: {html_out}")
    print(f"  -> 大小: {size_kb:.1f} KB")

    disk_shots = {f for f in os.listdir(shots_dir) if f.endswith(".jpg")}
    html_imgs  = len(re.findall(r'<figure class="screenshot">', html))
    mapping_shots = sum(len(item["screenshots"]) for item in mapping)
    consistent = (html_imgs == mapping_shots == len(disk_shots))
    print(f"\n=== 一致性验证 ===")
    print(f"  磁盘截图:  {len(disk_shots)} 张")
    print(f"  Mapping:   {mapping_shots} 张")
    print(f"  HTML <img>: {html_imgs} 个")
    print(f"  三者一致:   {'OK' if consistent else 'FAIL'}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
