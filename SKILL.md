---
name: bilibili-gameguide
description: |
  将B站游戏视频转换为图文攻略 HTML。
  当用户提供 B站视频 URL 或 BV号，并希望将视频内容转化为图文攻略时使用。
  全流程由 LLM 驱动，脚本仅做确定性操作（解析/截图/渲染），无任何硬编码。
  输出：一个可离线分享的纯静态 HTML 文件，含固定目录导航 + 摘要要点 + 截图。
  适用于：游戏攻略、玩法教程、通关指南等场景。
---

# Bilibili Game Guide Skill

## 核心理念

**LLM 做理解，脚本做执行。**

- LLM 负责：阅读字幕 → 理解内容 → 生成结构 → 提炼摘要
- Python 脚本负责：SRT 解析 → FFmpeg 截图 → HTML 渲染

**这意味着：这个 skill 对任何游戏都有效。** 不存在任何硬编码的游戏名称、关键词或正则表达式。

---

## Token 最小化设计

每个子段落仅输出：

```json
{
  "id": "s03_01",
  "heading": "### 御三家选择与性格机制",
  "level": 3,
  "start_sec": 66,
  "end_sec": 204,
  "concise_summary": "性格在六个属性中随机+20%一项、-10%一项，初始完美性格决定后续养成成本。PVP玩家最优选水蓝蓝。",
  "bullet_points": [
    "性格系统：随机+20%、-10%一项属性",
    "PVP最优：水蓝蓝（送迪莫，初期够强）",
    "不推荐火花，需氪金改性格"
  ]
}
```

- `concise_summary`：精炼概括，1-2 句，基于字幕生成，不凭空捏造
- `bullet_points`：关键要点，3-5 条，从字幕提取
- **原始字幕全文不写入 JSON** → token 消耗降低 90%+

---

## 工作流程（8 步）

### Step 0：检查依赖

#### Windows（PowerShell profile 被拦截时的解决方案）

如果 PowerShell 执行被 profile.ps1 拦截，使用 cmd 方式调用：

```bash
# 方式一：cmd /c（推荐，用于 WorkBuddy 环境）
cmd /c "python 脚本路径 --参数"

# 方式二：直接在 Python 中 import 执行
python -c "import sys; sys.path.insert(0, 'scripts路径'); from download_bilibili_cc import main; main()"
```

#### macOS / Linux

```bash
cd bilibili-gameguide/scripts
python check_dependencies.py
```

---

### Step 0.5：初始化下载根目录（新设备首次使用时必做）

**每台设备只需配置一次。** 此后所有视频下载文件夹都会统一维护在该目录下。

#### 方式一：命令行一步设置（推荐）

```bash
python check_dependencies.py --set-download-root "D:\BilibiliGuides"
# 或 macOS/Linux:
python check_dependencies.py --set-download-root "~/BilibiliGuides"
```

#### 方式二：交互式引导（首次调用下载脚本时自动触发）

如果尚未配置，运行下载脚本时会自动弹出引导提示：

```
======================================================
  bilibili-gameguide · 首次设置
======================================================
  这是您在本设备第一次使用本 skill。
  请指定一个本地文件夹作为视频下载根目录。
  今后所有下载的视频文件夹都会保存在该目录下。

  示例：
    D:\BilibiliGuides
    C:\Users\yourname\Videos\BilibiliGuides
    ~/BilibiliGuides

  请输入下载根目录路径：▌
```

#### 查看/修改已配置的根目录

```bash
# 查看当前配置
python check_dependencies.py --show-config
# 或
python download_bilibili_cc.py --url "" --show-download-root

# 迁移到新路径（直接重新设置）
python check_dependencies.py --set-download-root "E:\NewPath\BilibiliGuides"
```

> 配置持久化位置：`~/.workbuddy/skills/bilibili-gameguide/workspace_config.json`
> 每台设备独立配置，不随 skill 同步。

**Python 包**（截图脚本必须）：

| 包 | 用途 | 安装 |
|---|------|------|
| opencv-python | 视频帧读取 + 感知哈希 | `pip install opencv-python` |
| imagehash | pHash 感知哈希计算 | `pip install imagehash` |
| Pillow | 图像处理 | `pip install Pillow` |

**系统工具**：

| 工具 | 用途 | 放置位置 |
|------|------|----------|
| FFmpeg | 字幕提取 / 视频处理 | `~/.workbuddy/tools/ffmpeg.exe` |
| BBDown | 下载字幕 | `~/.workbuddy/tools/BBDown.exe` |

Windows 安装示例：
```powershell
# Python 包
pip install opencv-python imagehash Pillow

# FFmpeg
winget install ffmpeg
Copy-Item (Get-Command ffmpeg).Source "$env:USERPROFILE\.workbuddy\tools\ffmpeg.exe"

# BBDown：https://github.com/nilaoda/BBDown/releases → 解压到工具目录
```

### Step 1：准备阶段

#### 1.1 创建工作目录（规范命名）

**⚠️ 重要：每个任务必须使用规范命名的工作目录，且所有任务目录统一维护在设备配置的下载根目录下。**

调用下载脚本时，**无需指定 `--make-dir`**，脚本自动读取已配置的下载根目录并在其下创建任务目录：

```bash
# 最简调用（推荐）——自动使用配置的下载根目录
python scripts/download_bilibili_cc.py \
  --url "https://www.bilibili.com/video/BVxxxxx" \
  --cookie "SESSDATA=xxx"

# 显式指定根目录（覆盖配置，适合临时需求）
python scripts/download_bilibili_cc.py \
  --url "https://www.bilibili.com/video/BVxxxxx" \
  --make-dir "D:\临时目录" \
  --cookie "SESSDATA=xxx"
```

脚本自动：
1. 读取设备配置的下载根目录（未配置则交互式引导，仅首次）
2. 下载字幕获取视频标题
3. 按 `BV号_视频名称_任务时间` 命名并在根目录下创建任务目录
4. 将所有文件写入该目录
5. 返回 JSON 中包含 `task_dir` 字段

**命名规则：**
- BV号：从 URL 自动提取（`BVxxx` 格式）
- 视频名称：去除非法字符（`\\ / : * ? " < > |`），截断至 40 字
- 任务时间：`yyyymmdd_HHMM`（精确到分钟，避免重名）

#### 1.2 下载字幕（两步验证）+ 多P支持

**单P视频：**

```bash
python scripts/download_bilibili_cc.py \
  --url "https://www.bilibili.com/video/BVxxxxx" \
  --make-dir "工作区根目录" \
  --cookie "SESSDATA=xxx"
```

**多P视频（推荐使用 Python 调用 `download_multi_p`）：**

对于多P视频，每个分P独立下载到子目录，格式为 `p01_分P标题`：

#### HOOK: 多P视频复用主任务目录

**问题**：每次调用 create 新目录，导致视频/字幕分散

**脚本行为**：
```
1. 先扫描配置根目录下是否有该 BV 的主任务目录（有则复用，无则创建）
2. 分P放在主目录内，格式 p01_分P标题、p02_分P标题
3. 不重复创建 base 目录
```

```python
# LLM 可直接在脚本中调用
from download_bilibili_cc import download_multi_p, make_task_dir

# 先创建主任务目录
main_dir = make_task_dir("工作区根目录", "BVxxxxx", "视频主标题")

# 下载所有分P（字幕有效→正常pipeline；字幕无效→仅下载视频）
result = download_multi_p(
    url="https://www.bilibili.com/video/BVxxxxx",
    base_dir=main_dir,
    cookie="SESSDATA=xxx",
    video_only_on_fail=True,  # 字幕无效时仍下载视频
)
# result["pages"][i]["video_only"] == True → 该分P仅有视频，跳过 pipeline
```

脚本返回 JSON，结果判断：
- `success: true` → 字幕有效，继续 Step 2
- `success: false` + `video_only: true` → **仅下载视频，停止 pipeline，告知用户**

> **告知用户模板（字幕无效时）：**
> "该视频/分P（Pn）的 B站 AI 字幕不可用（字数不足或内容不相关）。\
> 视频文件已下载至 `task_dir`，但无法生成图文攻略。\
> 请提供其他视频，或手动上传 SRT/ASS 字幕文件。"

**⚠️ 关于字幕有效性判断：**
- 脚本内置**两阶段验证**：字幕内容不为空 **且** 标题关键词匹配率 ≥ 20%
- 不通过时：`success: false`，若 `video_only_on_fail=True` 则自动下载原视频
- 原视频保留在任务目录中，不会自动清理

### Step 2：LLM 生成语义结构 JSON

**输入**：字幕全文（SRT 原文）

**输出**：`video_structure.json`（JSON 文件，写入工作目录）

**LLM 行为**：
- 完整阅读所有字幕，理解视频主题和节奏
- 按话题自然切分章节，每个章节包含：
  - `heading`：标题（格式 `## xxx` 或 `### xxx`）
  - `level`：2 = 主章节，3 = 子章节
  - `start_sec` / `end_sec`：起止秒数
  - `concise_summary`：精炼概括段落（基于字幕内容生成，不凭空捏造）
  - `bullet_points`：关键要点列表（3-5 条，从字幕提取）

**章节切分原则**（无硬编码，由 LLM 自行判断）：
- 话题切换点（游戏从一个内容跳到另一个内容）
- 时间节奏（太长/太短的章节可合并/拆分）
- 内容密度（内容密集处可多设子章节，重复内容合并）

**示例 `video_structure.json` 结构**：

```json
{
  "_schema_version": "1.0",
  "video_title": "视频标题",
  "video_url": "https://www.bilibili.com/video/BVxxxx/",
  "sections": [
    {
      "id": "s01",
      "heading": "## 开场白",
      "level": 2,
      "start_sec": 0,
      "end_sec": 45,
      "subsections": [
        {
          "id": "s01_01",
          "heading": "### 视频封面与标题卡",
          "level": 3,
          "start_sec": 0,
          "end_sec": 29,
          "concise_summary": "手游前期均为等级驱动机制...",
          "bullet_points": ["等级驱动：等级不够无法抓精灵", "初期核心任务：冲等级"]
        }
      ],
      "concise_summary": "手游开局核心是冲等级推进主线...",
      "bullet_points": ["开局核心目标：升级魔法等级", "抓宠可解锁图鉴"]
    }
  ]
}
```

**注意**：
- `concise_summary` 必须基于字幕内容生成，不要凭空捏造
- `bullet_points` 应从字幕中提取关键数值、结论、建议
- 原始字幕全文**不要**写入 JSON（这是 token 最小化的关键）

### Step 3：运行脚本截图

```bash
cd bilibili-gameguide/scripts
python step1_parse_srt.py [config_path]
python step2_screenshot.py [config_path]
```

- 读取 `video_structure_with_subs.json` 中的语义结构
- 对每个 `###` 叶子段落：首帧 + **CV 感知哈希检测到的变化帧** + 末帧
- 跨段边界用感知哈希扫描，精确找到"内容切换点"
- 输出 `screenshot_mapping.json`（含截图归属 + 对应字幕片段）

**CV 检测参数**（在 `config.json` 的 `cv` 段配置）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `frame_interval_sec` | 1.0 | CV 扫描帧间隔（秒） |
| `pHash_threshold` | 15 | 感知哈希差异阈值（越大越严格） |
| `hist_threshold` | 0.20 | 直方图差异阈值 |
| `laplacian_threshold` | 30 | 清晰度变化阈值 |
| `min_gap_sec` | 5 | 相邻截图最小时间间隔（秒） |
| `min_window_sec` | 3 | 最短有效段落（秒），短于此直接返回首帧 |
| `max_per_window` | 8 | 每个段落最多截几张 |
| `boundary_pHash_threshold` | 10 | 跨段边界检测 pHash 阈值 |
| `boundary_hist_threshold` | 0.15 | 跨段边界检测直方图阈值 |

### Step 4：运行脚本生成 HTML

```bash
python step3_generate_html.py [config_path]
```

- 读取 `video_structure.json`（含 `concise_summary` + `bullet_points`）
- 读取 `screenshot_mapping.json`
- 组装最终 HTML（含 CSS，全部内联，无外部依赖）
- 输出 `game_guide.html`

### Step 5：生成 Markdown 完整笔记（可选）

```bash
python step4_generate_markdown.py [config_path]
```

- 读取 `video_structure_with_subs.json`（含字幕原文）
- 读取 `screenshot_mapping.json`
- 生成完整 Markdown，含：分级标题 + 精炼摘要 + 关键要点 + 字幕原文 + 截图
- 输出 `*_full_notes.md`

### Step 6：视频文件

> **原视频文件已保留在任务目录中，不再自动清理。**

pipeline 完成后任务目录结构：
```
BVxxx_视频名称_20260403_1820/
├── 视频标题.mp4              ← 原视频（保留）
├── 视频标题.ai-zh.srt        ← AI字幕
├── config.json
├── video_structure.json
├── video_structure_with_subs.json
├── screenshot_mapping.json
├── game_guide.html           ← 最终图文攻略
├── 视频标题_full_notes.md    ← 完整Markdown笔记
└── screenshots/
    └── *.jpg
```

**多P视频目录结构：**
```
BVxxx_视频主标题_20260403_1820/
├── p01_分P1标题/
│   ├── *.mp4
│   ├── game_guide.html
│   └── ...
├── p02_分P2标题/
│   ├── *.mp4           ← 无字幕分P：仅视频，无HTML
│   └── ...（video_only）
└── p03_分P3标题/
    └── ...
```

---

## 工具定义

### download_bilibili_cc

使用 `scripts/download_bilibili_cc.py` 下载字幕（内部调用 BBDown `--skip-ai false`）。

**参数：**
- `--url`：B站视频 URL 或 BV 号
- `--output`：输出目录（可选，默认 `./bilibili_subtitle`）
- `--cookie`：B站 SESSDATA（可选，可预先写入 `scripts/config.json`）

**返回 JSON 关键字段：**
| 字段 | 说明 |
|------|------|
| `success` | `true`=字幕有效可继续，`false`=无效停止 |
| `subtitle_file` | 字幕文件路径（失败时为 None） |
| `video_title` | 视频标题 |
| `char_count` | 纯文字字数 |
| `content_preview` | 内容预览前 300 字 |
| `message` | 状态描述 |

**Cookie 配置**（推荐写入 `scripts/config.json`，支持两种格式）：

```json
// 格式一：SESSDATA（旧格式，需要手动获取）
{
  "bilibili": {
    "cookie": "SESSDATA=你的SESSDATA值"
  }
}

// 格式二：DedeUserID + bili_ticket + bili_jct（通过 CDP 自动获取）
{
  "bilibili": {
    "cookie": "DedeUserID=27533021;bili_ticket=eyJ...;bili_jct=xxx"
  }
}
```

> **推荐**：使用 `python scripts/get_bili_cookie.py --save` 自动从浏览器获取登录态。

---

## 完整使用示例

### 示例输入

> 用户："帮我把这个 B站游戏视频做成图文攻略：https://www.bilibili.com/video/BV19bXmBpEyn/"

### Step 1：下载视频+字幕（自动使用配置根目录）

> **新工作流**：先下载视频获取准确标题 → 快速检测字幕（有则复制，无则跳过）→ 避免无效等待。
> - BBDown 使用 `--skip-mux` 保留独立字幕文件，实现快速检测
> - 无字幕时直接返回 `video_only: true`，耗时约 3-4 秒

#### Windows（cmd 方式，防止 PowerShell profile 拦截）

```bash
cmd /c "python C:\Users\yourname\.workbuddy\skills\bilibili-gameguide\scripts\download_bilibili_cc.py --url https://www.bilibili.com/video/BV19bXmBpEyn/ --cookie SESSDATA=xxx"
```

#### macOS / Linux

```bash
python scripts/download_bilibili_cc.py \
  --url "https://www.bilibili.com/video/BV19bXmBpEyn/" \
  --cookie "SESSDATA=xxx"
```

> 首次使用时会提示设置下载根目录（仅一次）。

**工作流程**：
1. **Step 1/3** - 下载视频获取准确标题（目录名与实际视频文件一致）
2. **Step 2/3** - 下载字幕到同一目录
3. **Step 3/3** - 返回结果

返回 JSON 示例：
```json
{
  "success": true,
  "subtitle_file": "/工作区/BV19bXmBpEyn_4.3版本攻略_20260403_1820/视频标题.ai-zh.srt",
  "video_title": "4.3版本攻略",
  "char_count": 2246,
  "task_dir": "/工作区/BV19bXmBpEyn_4.3版本攻略_20260403_1820",
  "message": "字幕下载成功，共 2246 字"
}
```
- `success: true` + `task_dir` → 字幕有效，继续，使用 `task_dir` 作为工作目录
- `success: false` + 有 `task_dir` → 无字幕但视频已下载，任务目录包含 `.mp4` 文件

### Step 2：LLM 阅读字幕并生成结构

LLM 阅读字幕全文后，生成 `video_structure.json`（写入 `task_dir`）。

### Step 3：截图

```bash
python check_dependencies.py
python step2_screenshot.py task_dir/config.json
```

### Step 4：生成 HTML

```bash
python step3_generate_html.py task_dir/config.json
```

### Step 5：生成 Markdown 完整笔记（可选）

```bash
python step4_generate_markdown.py task_dir/config.json
```

### 最终输出

`task_dir/game_guide.html`，包含：
- 视频信息面板（B站链接、UP主、时长等）
- 左侧固定目录导航（可点击跳转）
- 每个章节的精炼摘要 + 关键要点标签
- 每个子章节的截图（带时间戳和标注）

原视频保留在 `task_dir` 中，不自动删除。

---

## 配置说明

所有配置通过 `config.json` 完成，无硬编码。

### video 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `file` | 是 | 视频文件名（.mp4），放在工作目录 |
| `subtitle` | 是 | 字幕文件名（.srt），从 BBDown 下载 |
| `url` | 是 | B站视频 URL |
| `bv_id` | 否 | BV号 |
| `title` | 是 | 视频标题 |
| `uploader` | 否 | UP主名称 |
| `duration_sec` | 否 | 视频总时长（秒） |
| `publish_date` | 否 | 发布时间 |
| `description` | 否 | 视频简介 |

### html 字段

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `title` | 游戏攻略笔记 | HTML 页面标题 |
| `accent_color` | #00b4d8 | 主色调 |
| `bg_color` | #0f1419 | 背景色（暗色主题） |
| `card_color` | #1c2128 | 卡片背景色 |
| `text_color` | #e6edf3 | 正文字体颜色 |
| `border_color` | #30363d | 边框颜色 |
| `tag_color` | #58a6ff | 标签/强调色 |

---

## 故障排除

### 字幕下载后 `success: false`
- **原因**：B站 ASR AI 字幕对该视频不可用（内容为空或与标题不相关）
- **行为**：若 `video_only_on_fail=True`（默认），原视频仍会下载到任务目录
- **解决**：告知用户换一个视频，或手动提供 SRT/ASS 字幕文件

### BBDown 未找到
- 确保 BBDown.exe 在 PATH 中，或放入 `~/.workbuddy/tools/BBDown.exe`
- Windows 已知路径：`C:\WorkBuddy_BBDown\BBDown.exe`（自动检测）

### CDP Proxy 启动失败
- 确保 Chrome 已开启 remote debugging：`--remote-debugging-port=9222`
- 检查端口 3456 是否被占用：`netstat -ano | findstr 3456`
- 手动启动 CDP Proxy：`node C:\Users\jinzh\.workbuddy\skills\web-access\scripts\cdp-proxy.mjs`

### CDP 无法获取 SESSDATA
- **原因**：B站将 SESSDATA 设为 HttpOnly，JavaScript 无法读取
- **解决**：运行 `BBDown.exe login` 扫码获取完整 SESSDATA，或使用当前 cookie 下载公开视频

### 视频无字幕
- 视频文件已下载，不会自动清理
- 请用户提供带字幕的视频，或手动上传 SRT/ASS 字幕文件

### 截图失败
- 检查 FFmpeg 已安装且在 PATH 中
- 检查视频文件存在且路径正确
- Windows 安装：`winget install ffmpeg`

### HTML 中截图路径错误
- 确保 `config.json` 的 `screenshots_dir` 与实际截图目录一致
- HTML 截图路径为相对于 HTML 文件的路径

---

## 与 bilibili-cc-to-notion 的区别

| | bilibili-cc-to-notion | bilibili-gameguide |
|--|----------------------|--------------------|
| 输出 | Notion 页面 | 静态 HTML |
| 内容 | 字幕原文 | 精炼摘要 |
| 场景 | 学习笔记 | 游戏攻略 |

---

## 文件结构

```
bilibili-gameguide/
├── SKILL.md                          # 本文件
└── scripts/
    ├── check_dependencies.py          # 依赖检查（Python 包 + 系统工具）
    ├── config_template.json           # 配置文件模板
    ├── config.json                    # Cookie 等用户配置
    ├── download_bilibili_cc.py        # BBDown 下载字幕
    ├── get_bili_cookie.py             # CDP 自动获取 B站 cookie（依赖 web-access skill）
    ├── step1_parse_srt.py             # SRT 解析
    ├── step2_screenshot.py            # CV 感知哈希截图
    ├── step3_generate_html.py         # HTML 生成（图文攻略）
    ├── step4_generate_markdown.py     # Markdown 生成（完整笔记）
    └── run_pipeline.py                # 一键运行
```

---

## 依赖

**Python 包**（`pip install`）：

| 包 | 用途 |
|------|------|
| opencv-python | 视频帧读取 + 感知哈希 |
| imagehash | pHash 感知哈希计算 |
| Pillow | 图像处理 |

**系统工具**（`~/.workbuddy/tools/`）：

| 工具 | 用途 |
|------|------|
| FFmpeg | 字幕提取 / 视频处理 |
| BBDown | 下载字幕 |
| Node.js | CDP Proxy 运行（web-access） |

### Web-Access Skill（CDP 自动获取 Cookie）

**用途**：通过 Chrome DevTools Protocol (CDP) 从浏览器自动提取 B站登录 cookie，替代手动复制。

**工作原理**：
1. 启动 CDP Proxy（连接本地 Chrome）
2. 从 B站标签页提取 cookie
3. 保存到 `config.json` 供 BBDown 使用

**依赖**：
- `web-access` skill（CDP Proxy 脚本）
- Node.js（已安装）
- Chrome 浏览器 + 开启 remote debugging

**Cookie 格式**：
```json
{
  "bilibili": {
    "cookie": "DedeUserID=xxx;bili_ticket=xxx;bili_jct=xxx"
  }
}
```

> **注意**：B站将 SESSDATA 设为 HttpOnly，无法通过 JavaScript 读取。当前 cookie 可下载**公开视频**，如需下载**会员内容**需运行 `BBDown.exe login` 扫码获取完整 SESSDATA。

**使用方式**：

#### 方式一：自动获取（推荐）

```bash
python scripts/get_bili_cookie.py --save
```

脚本会：
1. 检查 CDP Proxy 是否运行，如未运行则自动启动
2. 查找 B站标签页
3. 提取 `DedeUserID` + `bili_ticket` + `bili_jct`
4. 自动保存到 `scripts/config.json`

#### 方式二：手动启动 CDP Proxy（需要先在 Chrome 中开启 remote debugging）

```bash
# Chrome 启动参数
--remote-debugging-port=9222

# 启动 CDP Proxy
# Windows:
node C:\Users\jinzh\.workbuddy\skills\web-access\scripts\cdp-proxy.mjs

# macOS / Linux:
node ~/.workbuddy/skills/web-access/scripts/cdp-proxy.mjs
```

验证 CDP Proxy 是否运行：
```bash
curl http://127.0.0.1:3456/targets
```

#### 方式三：手动复制 cookie

1. 登录 B站
2. 打开开发者工具 (F12) → Application → Cookies → bilibili.com
3. 复制 `DedeUserID`、`bili_ticket`、`bili_jct` 三个值
4. 写入 `config.json`：
   ```json
   {
     "bilibili": {
       "cookie": "DedeUserID=xxx;bili_ticket=xxx;bili_jct=xxx"
     }
   }
   ```

---

安装后用 `python check_dependencies.py` 验证。

---

## 注意事项

1. **无硬编码**：章节切分、摘要生成全部由 LLM 完成，对任何游戏均有效
2. **Token 优先**：原始字幕不写入 `video_structure.json`，仅用 `concise_summary` + `bullet_points`
3. **截图需视频文件**：Step 2 需要本地视频文件（720P+）
4. **HTML 可离线分享**：纯静态，截图通过相对路径引用
