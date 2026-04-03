"""
=====================================================================
bilibili-gameguide · 依赖检查脚本 v4（极速版）
=====================================================================

三层路径优先级（始终按此顺序查找）：
  Layer 1: ~/.workbuddy/tools/          （项目工具目录，始终最优先）
  Layer 2: tool_registry.json           （本地已注册路径）
  Layer 3: PATH                         （全局搜索，仅 --discover 时触发）

注册表持久化：~/.workbuddy/tools/tool_registry.json

用法：
  python check_dependencies.py                  # 极速检查（无 subprocess）
  python check_dependencies.py -v                # 带版本信息（触发 subprocess，较慢）
  python check_dependencies.py --discover ffmpeg # 扫描 PATH 并注册
  python check_dependencies.py --install ffmpeg  # 直接下载安装
  python check_dependencies.py --list            # 列出当前注册表

返回码：
  0 = 所有依赖就绪
  1 = 缺少依赖
=====================================================================
"""

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import io
from pathlib import Path
from typing import Optional

# -------------------------------------------------------------------
# 路径常量
# -------------------------------------------------------------------
TOOLS_DIR = Path.home() / ".workbuddy" / "tools"
REGISTRY_FILE = TOOLS_DIR / "tool_registry.json"
TOOLS_DIR.mkdir(parents=True, exist_ok=True)

# bilibili-gameguide skill 配置目录（与 tool_registry.json 同级）
SKILL_DIR = Path.home() / ".workbuddy" / "skills" / "bilibili-gameguide"
WORKSPACE_CONFIG_FILE = SKILL_DIR / "workspace_config.json"


# -------------------------------------------------------------------
# Workspace 配置（下载根目录等跨设备持久化设置）
# -------------------------------------------------------------------
def load_workspace_config() -> dict:
    """读取 workspace_config.json，不存在则返回空 dict。"""
    if WORKSPACE_CONFIG_FILE.exists():
        try:
            with open(WORKSPACE_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_workspace_config(cfg: dict) -> None:
    """持久化保存 workspace_config.json。"""
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(WORKSPACE_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_download_root() -> Optional[Path]:
    """
    获取当前设备配置的下载根目录。
    未配置时返回 None。
    """
    cfg = load_workspace_config()
    raw = cfg.get("download_root", "")
    if raw:
        p = Path(raw)
        if p.exists():
            return p
        # 目录不存在则尝试创建（用户可能只是换了盘符/挂载点）
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            return None
    return None


def set_download_root(path_str: str) -> Path:
    """
    设置并持久化下载根目录，同时创建该目录。
    返回 Path 对象。
    """
    p = Path(path_str).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    cfg = load_workspace_config()
    cfg["download_root"] = str(p)
    save_workspace_config(cfg)
    return p


def ensure_download_root(interactive: bool = True) -> Optional[Path]:
    """
    确保下载根目录已配置。
    - 已配置且存在 → 直接返回
    - 未配置 + interactive=True → 交互式询问并保存
    - 未配置 + interactive=False → 返回 None
    """
    root = get_download_root()
    if root:
        return root

    if not interactive:
        return None

    print("\n" + "=" * 60)
    print("  bilibili-gameguide · 首次设置")
    print("=" * 60)
    print("  这是您在本设备第一次使用本 skill。")
    print("  请指定一个本地文件夹作为视频下载根目录。")
    print("  今后所有下载的视频文件夹都会保存在该目录下。")
    print()
    print("  示例：")
    print("    D:\\BilibiliGuides")
    print("    C:\\Users\\yourname\\Videos\\BilibiliGuides")
    print("    ~/BilibiliGuides")
    print()

    while True:
        user_input = input("  请输入下载根目录路径：").strip().strip('"').strip("'")
        if not user_input:
            print("  [!] 路径不能为空，请重新输入。")
            continue

        p = Path(user_input).expanduser().resolve()
        try:
            p.mkdir(parents=True, exist_ok=True)
            root = set_download_root(str(p))
            print(f"\n  [OK] 下载根目录已设置：{root}")
            print(f"       配置已保存至：{WORKSPACE_CONFIG_FILE}")
            print("=" * 60 + "\n")
            return root
        except Exception as e:
            print(f"  [X] 无法创建目录：{e}，请重新输入。")

# Layer 0: 已知非标准安装路径（conda/PowerShell PATH 失效时仍可用）
# 结构: tool_name -> list of possible Path objects
KNOWN_ROOTS: dict[str, list[Path]] = {
    "ffmpeg": [
        Path(r"C:\WorkBuddy_FFmpeg\ffmpeg.exe"),
        Path(r"C:\WorkBuddy_FFmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        Path.home() / ".workbuddy" / "tools" / "ffmpeg.exe",
    ],
    "bbdown": [
        Path(r"C:\WorkBuddy_BBDown\BBDown.exe"),
        Path.home() / ".workbuddy" / "tools" / "BBDown.exe",
    ],
    "BBDown": [
        Path(r"C:\WorkBuddy_BBDown\BBDown.exe"),
        Path.home() / ".workbuddy" / "tools" / "BBDown.exe",
    ],
}


# -------------------------------------------------------------------
# 注册表读写
# -------------------------------------------------------------------
def load_registry() -> dict:
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_registry(registry: dict) -> None:
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def register_tool(name: str, path: str, version_hint: str = "") -> dict:
    registry = load_registry()
    entry = {"name": name, "path": str(path), "version_hint": version_hint}
    registry[name] = entry
    save_registry(registry)
    return entry


def get_registered(name: str) -> Optional[Path]:
    registry = load_registry()
    entry = registry.get(name)
    if entry and entry.get("path"):
        p = Path(entry["path"])
        if p.exists():
            return p
    return None


# -------------------------------------------------------------------
# 三层路径查找（仅 Layer 1 + 2，无 subprocess）
# -------------------------------------------------------------------
def find_tool(name: str, extensions=("", ".exe")) -> Optional[Path]:
    """
    三层路径查找，顺序: Layer 0(KNOWN_ROOTS) → Layer 1(project) → Layer 2(registry)。
    Layer 0 找到后自动注册到 Layer 2，避免下次再搜。
    不碰 PATH，不触发 conda 初始化。
    """
    # Layer 0: KNOWN_ROOTS（已知非标准安装位置）
    known = KNOWN_ROOTS.get(name, [])
    for base in known:
        for ext in extensions:
            p = base.parent / (base.stem + ext) if base.suffix != ext else base
            if p.exists():
                register_tool(name, p)   # 写入注册表，下次直接命中 Layer 2
                return p
        # 直接文件路径
        if base.exists():
            register_tool(name, base)
            return base

    # Layer 1: project tools dir
    for ext in extensions:
        p = TOOLS_DIR / (name + ext)
        if p.exists():
            return p

    # Layer 2: registry
    return get_registered(name)


# -------------------------------------------------------------------
# Layer 3：PATH 扫描（仅 discover 时使用）
# -------------------------------------------------------------------
def _get_version(exe: Path) -> str:
    """获取版本信息（触发 subprocess，较慢）。"""
    try:
        r = subprocess.run(
            [str(exe), "-version"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout.split("\n")[0][:70]
    except Exception:
        pass
    return ""


def find_on_path(name: str) -> Optional[Path]:
    found = shutil.which(name)
    if found:
        p = Path(found)
        register_tool(name, p, _get_version(p))
        return p
    return None


# -------------------------------------------------------------------
# 交互式 Hook：依赖缺失时询问用户
# -------------------------------------------------------------------
def on_missing_tool(name: str, display_name: str = "") -> Optional[Path]:
    if not display_name:
        display_name = name

    print(f"\n[!] {display_name} not found in:")
    print(f"    Layer 1 (project)  : {TOOLS_DIR}")
    registry = load_registry()
    reg_path = registry.get(name, {}).get("path", "n/a")
    print(f"    Layer 2 (registry)  : {reg_path}")
    print(f"    Layer 3 (PATH)     : not scanned\n")

    print(f"  Choose how to resolve '{display_name}':\n")
    print(f"    [1] Scan PATH (Layer 3) to find existing installation")
    print(f"    [2] Enter path manually")
    print(f"    [3] Download and install automatically")

    if name == "ffmpeg":
        print(f"         (ffmpeg: downloads from github.com/GyanD/codexffmpeg)")
    elif name == "BBDown":
        print(f"         (BBDown: downloads from github.com/nilaoda/BBDown)")
    print()

    while True:
        choice = input(f"  Enter choice [1/2/3] (or 'q' to cancel): ").strip().lower()
        if choice == "q" or choice == "取消":
            print("  [cancelled]")
            return None

        if choice == "1":
            print(f"\n  Scanning PATH for '{name}'...")
            found = find_on_path(name)
            if found:
                print(f"  [OK] Found and registered: {found}")
                return found
            print(f"  [X]  Not found in PATH.")
            continue

        elif choice == "2":
            path_input = input(f"  Enter full path to {display_name}: ").strip().strip('"').strip("'")
            if not path_input:
                print("  [cancelled]")
                return None
            p = Path(path_input)
            if p.exists() and p.is_file():
                register_tool(name, p, _get_version(p))
                print(f"  [OK] Registered: {p}")
                return p
            print(f"  [X]  File not found: {p}")
            continue

        elif choice == "3":
            if name == "ffmpeg":
                result = _download_ffmpeg()
                if result:
                    return result
                continue
            elif name == "BBDown":
                result = _download_bbdown()
                if result:
                    return result
                continue
            else:
                print(f"  [X] Auto-install not supported for '{name}'. Use option 1 or 2.")
                continue

        print("  Invalid choice. Enter 1, 2, 3, or 'q'.")


# -------------------------------------------------------------------
# 自动下载安装
# -------------------------------------------------------------------
def _download_ffmpeg() -> Optional[Path]:
    url = "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip"
    zip_name = TOOLS_DIR / "ffmpeg.zip"
    temp_dir = TOOLS_DIR / "ffmpeg_extracted"

    print(f"\n  Downloading FFmpeg 7.1 from GitHub...")
    print(f"  This may take a minute...")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [X] Download failed: {e}")
        return None

    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(TOOLS_DIR / "ffmpeg_extracted")
    except Exception as e:
        print(f"  [X] Extract failed: {e}")
        return None

    for root, dirs, files in temp_dir.walk():
        for fname in files:
            if fname.lower() == "ffmpeg.exe":
                src = root / fname
                dst = TOOLS_DIR / "ffmpeg.exe"
                shutil.copy2(src, dst)
                shutil.rmtree(temp_dir)
                if zip_name.exists():
                    zip_name.unlink()
                register_tool("ffmpeg", dst, _get_version(dst))
                print(f"  [OK] Installed: {dst}")
                return dst

    print("  [X] ffmpeg.exe not found in archive.")
    return None


def _download_bbdown() -> Optional[Path]:
    api_url = "https://api.github.com/repos/nilaoda/BBDown/releases/latest"
    print(f"\n  Fetching latest BBDown release info...")
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            release = json.loads(resp.read())
            browser_url = release["assets"][0]["browser_download_url"]
    except Exception as e:
        print(f"  [X] Failed to get release info: {e}")
        return None

    dst = TOOLS_DIR / "BBDown.exe"
    print(f"  Downloading BBDown...")
    try:
        req = urllib.request.Request(browser_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(dst, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"  [X] Download failed: {e}")
        return None

    register_tool("BBDown", dst, _get_version(dst))
    print(f"  [OK] Installed: {dst}")
    return dst


# -------------------------------------------------------------------
# Python 包检查（无 subprocess，秒级完成）
# -------------------------------------------------------------------
def check_python() -> tuple[bool, str]:
    v = sys.version_info
    return True, f"Python {v.major}.{v.minor}.{v.micro}"


def check_cv2() -> tuple[bool, str]:
    try:
        import cv2
        return True, f"opencv-python ({cv2.__version__})"
    except ImportError:
        return False, "opencv-python (run: pip install opencv-python)"


def check_imagehash() -> tuple[bool, str]:
    try:
        import imagehash
        return True, "imagehash"
    except ImportError:
        return False, "imagehash (run: pip install imagehash)"


def check_pillow() -> tuple[bool, str]:
    try:
        import PIL
        return True, "Pillow"
    except ImportError:
        return False, "Pillow (run: pip install Pillow)"


# -------------------------------------------------------------------
# 主检查流程
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="bilibili-gameguide dependency checker")
    parser.add_argument("--discover", metavar="toolname",
                        help="Force PATH scan and register")
    parser.add_argument("--install", metavar="toolname",
                        help="Download and install automatically")
    parser.add_argument("--list", action="store_true",
                        help="Show current registry")
    parser.add_argument("-v", "--version", action="store_true",
                        help="Show version info (slower, triggers subprocess)")
    parser.add_argument("--set-download-root", metavar="PATH",
                        help="设置本设备的下载根目录并保存（首次使用或迁移时调用）")
    parser.add_argument("--show-config", action="store_true",
                        help="显示当前 workspace 配置（下载根目录等）")
    args = parser.parse_args()

    # --set-download-root: 手动指定/更新下载根目录
    if args.set_download_root:
        try:
            root = set_download_root(args.set_download_root)
            print(f"[OK] 下载根目录已设置：{root}")
            print(f"     配置文件：{WORKSPACE_CONFIG_FILE}")
            return 0
        except Exception as e:
            print(f"[X] 设置失败：{e}")
            return 1

    # --show-config: 显示当前 workspace 配置
    if args.show_config:
        cfg = load_workspace_config()
        print("=" * 60)
        print("  bilibili-gameguide Workspace Config")
        print("=" * 60)
        print(f"  配置文件：{WORKSPACE_CONFIG_FILE}")
        if not cfg:
            print("  (未配置 — 首次下载时会提示初始化)")
        else:
            root = cfg.get("download_root", "(未设置)")
            exists = Path(root).exists() if root != "(未设置)" else False
            status = "[OK]" if exists else "[目录不存在]"
            print(f"  下载根目录 {status}：{root}")
        print("=" * 60)
        return 0

    # --list: 仅显示注册表
    if args.list:
        print("=" * 60)
        print("  Tool Registry")
        print("=" * 60)
        print(f"  File: {REGISTRY_FILE}")
        print(f"  Dir : {TOOLS_DIR}")
        print("-" * 60)
        registry = load_registry()
        if not registry:
            print("  (empty)\n")
        else:
            for name, entry in sorted(registry.items()):
                p = Path(entry.get("path", "n/a"))
                status = "[OK]" if p.exists() else "[MISSING]"
                print(f"  {status} {name}: {entry.get('path', 'n/a')}")
        return 0

    # --discover: 强制 PATH 扫描
    if args.discover:
        print(f"[discover] Scanning PATH for: {args.discover}")
        found = find_on_path(args.discover)
        if found:
            print(f"[OK] Found and registered: {found}")
            return 0
        print(f"[X] Not found in PATH.")
        return 1

    # --install: 直接下载安装
    if args.install:
        name = args.install
        if name == "ffmpeg":
            result = _download_ffmpeg()
        elif name == "bbdown":
            result = _download_bbdown()
        else:
            print(f"[X] Auto-install not supported for '{name}'.")
            return 1
        return 0 if result else 1

    # -----------------------------------------------------------
    # 标准检查（Layer 1 + Layer 2，无 subprocess）
    # -----------------------------------------------------------
    print("=" * 60)
    print("  Dependency Check (fast mode, no subprocess)")
    print("=" * 60)
    print(f"  Project dir : {TOOLS_DIR}")
    print(f"  Registry    : {REGISTRY_FILE}")
    # 显示下载根目录配置状态
    dl_root = get_download_root()
    if dl_root:
        print(f"  Download dir: {dl_root}")
    else:
        print(f"  Download dir: (未配置 — 首次下载时会提示)")
    print("-" * 60)

    # Python 包
    pkg_checks = [
        ("Python",        check_python),
        ("opencv-python", check_cv2),
        ("imagehash",     check_imagehash),
        ("Pillow",        check_pillow),
    ]
    pkg_all_ok = True
    for label, fn in pkg_checks:
        ok, msg = fn()
        status = "OK" if ok else "MISSING"
        print(f"  [{status:8}] {msg}")
        if not ok:
            pkg_all_ok = False

    print("-" * 60)

    # 系统工具
    tool_checks = [
        ("ffmpeg",  "FFmpeg"),
        ("bbdown", "BBDown"),
    ]
    tool_all_ok = True
    resolved: dict[str, Optional[Path]] = {}

    for tool_name, display_name in tool_checks:
        exe = find_tool(tool_name)
        if exe:
            if args.version:
                ver = _get_version(exe)
                hint = f"  ({ver[:50]})" if ver else ""
                print(f"  [OK      ] {display_name}  {exe}{hint}")
            else:
                print(f"  [OK      ] {display_name}  {exe}")
            resolved[tool_name] = exe
        else:
            print(f"  [MISSING ] {display_name}  not found")
            resolved[tool_name] = None
            tool_all_ok = False

    print("-" * 60)

    if pkg_all_ok and tool_all_ok:
        print("\n  [OK] All dependencies ready.\n")
        return 0

    # 缺少 Python 包
    if not pkg_all_ok:
        missing_pkgs = [label for label, fn in pkg_checks if not fn()[0]]
        print(f"\n[!] Missing Python packages:")
        print(f"  pip install {' '.join(missing_pkgs)}\n")

    # 缺少系统工具 → 交互 Hook
    if not tool_all_ok:
        for tool_name, display_name in tool_checks:
            if resolved[tool_name] is None:
                found = on_missing_tool(tool_name, display_name)
                if found:
                    print(f"  [OK] {display_name} resolved: {found}")
                else:
                    print(f"  [skipped] {display_name} not resolved")

    # 最终重新检查
    print("\n" + "=" * 60)
    print("  Re-checking...\n")

    still_missing = []
    for tool_name, display_name in tool_checks:
        exe = find_tool(tool_name)
        if exe:
            if args.version:
                ver = _get_version(exe)
                hint = f"  ({ver[:50]})" if ver else ""
                print(f"  [OK      ] {display_name}  {exe}{hint}")
            else:
                print(f"  [OK      ] {display_name}  {exe}")
        else:
            print(f"  [MISSING ] {display_name}")
            still_missing.append(display_name)

    print("-" * 60)
    if still_missing:
        print(f"\n[!] Still missing: {', '.join(still_missing)}\n")
        return 1

    print("\n  [OK] All dependencies ready.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
