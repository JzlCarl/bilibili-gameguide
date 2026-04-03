# Bilibili Game Guide

B站游戏视频 → 图文攻略 HTML。全流程 LLM 驱动，脚本仅做确定性操作。

## 功能特性

- **自动下载**：BBDown 下载视频 + 字幕（支持多 P）
- **智能截图**：CV 感知哈希去重（pHash + 直方图 + Laplacian）
- **LLM 驱动**：生成结构化摘要 + 要点，token 降低 90%+
- **多格式输出**：HTML 图文攻略 + Markdown 完整笔记
- **CDP 自动获取 Cookie**：通过 web-access skill 从浏览器提取登录态
- **跨平台**：支持 Windows / macOS / Linux

## 快速开始

### 1. 检查依赖

```bash
cd bilibili-gameguide/scripts
python check_dependencies.py
```

### 2. 配置 Cookie（推荐 CDP 自动获取）

```bash
# 自动从浏览器获取登录 cookie（推荐）
python get_bili_cookie.py --save

# 或手动编辑 config.json
```

### 3. 下载视频 + 字幕

```bash
# Windows
cmd /c "python scripts/download_bilibili_cc.py --url https://www.bilibili.com/video/BVxxxx/"

# macOS / Linux
python scripts/download_bilibili_cc.py --url "https://www.bilibili.com/video/BVxxxx/"
```

### 4. 运行 Pipeline

```bash
cd bilibili-gameguide/scripts
python run_pipeline.py
```

### 5. 查看结果

打开 `game_guide.html` 即可查看图文攻略。

## 文件结构

```
bilibili-gameguide/
├── SKILL.md                          # 完整使用文档
├── README.md                         # 本文件
├── scripts/
│   ├── check_dependencies.py          # 依赖检查 + 工具查找
│   ├── config_template.json           # 配置模板
│   ├── config.json                    # 用户配置
│   ├── download_bilibili_cc.py        # BBDown 下载（支持多 P）
│   ├── get_bili_cookie.py             # CDP 自动获取 Cookie
│   ├── step1_parse_srt.py             # SRT 解析
│   ├── step2_screenshot.py            # CV 感知哈希截图
│   ├── step3_generate_html.py         # HTML 生成
│   ├── step4_generate_markdown.py    # Markdown 生成
│   └── run_pipeline.py                # 一键运行
```

## 依赖

- Python 3.7+
- FFmpeg（截图）
- BBDown（下载字幕）
- Node.js（CDP Proxy，用于自动获取 Cookie）

## 主题定制

编辑 `config.json` 的 `html` 字段即可自定义配色：

```json
"html": {
  "accent_color": "#00b4d8",
  "bg_color": "#0f1419",
  "card_color": "#1c2128"
}
```

## 更新日志

### 2026-04-04
- 集成 web-access skill（CDP 自动获取 Cookie）
- 支持 Windows / macOS / Linux 三平台
- 新增 `get_bili_cookie.py` 脚本
- 优化跨平台路径适配

### 2026-04-03
- 多 P 视频支持（每 P 独立子目录）
- 设备下载根目录持久化
- 无字幕降级（视频仅下载模式）

### 2026-04-02
- 初始版本
- CV 感知哈希截图（pHash + 直方图 + Laplacian）
- LLM 生成结构化摘要
- HTML / Markdown 双输出