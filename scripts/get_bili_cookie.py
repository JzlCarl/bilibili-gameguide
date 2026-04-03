#!/usr/bin/env python3
"""
通过 CDP (Chrome DevTools Protocol) 从浏览器获取 B站登录态 cookie
用法: python get_bili_cookie.py [--save]
"""

import subprocess
import sys
import os
import time
import re
import json
import platform

CDP_PROXY_URL = "http://127.0.0.1:3456"

# 根据系统选择配置路径
if platform.system() == "Windows":
    CONFIG_PATH = r"C:\Users\jinzh\.workbuddy\skills\bilibili-gameguide\scripts\config.json"
else:
    # macOS / Linux
    home = os.path.expanduser("~")
    CONFIG_PATH = os.path.join(home, ".workbuddy", "skills", "bilibili-gameguide", "scripts", "config.json")

def check_cdp_proxy():
    """检查 CDP Proxy 是否运行"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"{CDP_PROXY_URL}/targets"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except:
        return False

def get_bili_targets():
    """获取 B站相关的浏览器标签页"""
    result = subprocess.run(
        ["curl", "-s", f"{CDP_PROXY_URL}/targets"],
        capture_output=True
    )
    if result.returncode != 0:
        return None
    
    try:
        targets = json.loads(result.stdout.decode('utf-8', errors='replace'))
        for t in targets:
            url = t.get("url", "")
            if "bilibili.com" in url:
                return t.get("id"), url
    except:
        pass
    return None

def get_cookie_from_target(target_id):
    """从指定标签页获取 cookie"""
    # 获取完整 cookie 字符串
    cmd = f'curl -s -X POST "{CDP_PROXY_URL}/eval?target={target_id}" -H "Content-Type: text/plain" -d "document.cookie"'
    result = subprocess.run(cmd, shell=True, capture_output=True)
    
    try:
        data = json.loads(result.stdout.decode('utf-8', errors='replace'))
        cookie_str = data.get("value", "")
        
        # 提取关键字段
        dede_user_id = re.search(r'DedeUserID=([^;]+)', cookie_str)
        bili_ticket = re.search(r'bili_ticket=([^;]+)', cookie_str)
        bili_jct = re.search(r'bili_jct=([^;]+)', cookie_str)
        
        if dede_user_id and bili_ticket:
            cookie_parts = []
            cookie_parts.append(f"DedeUserID={dede_user_id.group(1)}")
            cookie_parts.append(f"bili_ticket={bili_ticket.group(1)}")
            if bili_jct:
                cookie_parts.append(f"bili_jct={bili_jct.group(1)}")
            
            return ";".join(cookie_parts)
    except Exception as e:
        print(f"解析 cookie 失败: {e}")
    
    return None

def start_cdp_proxy():
    """启动 CDP Proxy"""
    import platform
    node_path = "node"
    
    # 根据系统选择 CDP Proxy 路径
    if platform.system() == "Windows":
        script_path = r"C:\Users\jinzh\.workbuddy\skills\web-access\scripts\cdp-proxy.mjs"
    else:
        # macOS / Linux
        home = os.path.expanduser("~")
        script_path = os.path.join(home, ".workbuddy", "skills", "web-access", "scripts", "cdp-proxy.mjs")
    
    # 后台启动
    subprocess.Popen(
        [node_path, script_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )
    print("CDP Proxy 已启动...")
    time.sleep(2)

def save_cookie_to_config(cookie):
    """保存 cookie 到 config.json"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        config["cookie"] = cookie
        
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"[OK] Cookie saved to {CONFIG_PATH}")
    except Exception as e:
        print(f"保存配置失败: {e}")

def main():
    print("=== BiliBili Cookie Get Tool ===")
    
    # 1. 检查 CDP Proxy
    if not check_cdp_proxy():
        print("[!] CDP Proxy not running, starting...")
        start_cdp_proxy()
    
    # 2. 查找 B站标签页
    bili_info = get_bili_targets()
    if not bili_info:
        print("[!] 未找到 B站标签页，请在浏览器中打开 bilibili.com")
        sys.exit(1)
    
    target_id, url = bili_info
    print(f"[i] 找到 B站页面: {url}")
    
    # 3. 获取 cookie
    print("[i] 提取 cookie...")
    cookie = get_cookie_from_target(target_id)
    
    if cookie:
        print(f"[OK] 获取到 cookie: {cookie[:50]}...")
        
        # 保存到配置
        if "--save" in sys.argv:
            save_cookie_to_config(cookie)
        
        print("\n使用此 cookie 调用 BBDown:")
        print(f'  BBDown.exe <url> -c "{cookie}"')
    else:
        print("[X] 无法获取 cookie，可能未登录 B站")
        sys.exit(1)

if __name__ == "__main__":
    main()