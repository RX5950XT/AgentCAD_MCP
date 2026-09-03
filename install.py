#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""把 AgentCAD 裝進 FreeCAD，並註冊 MCP server。

    python install.py              # 裝好並註冊 MCP
    python install.py --check      # 只檢查現況，不動任何東西
    python install.py --uninstall  # 移除

自己找 FreeCAD 的使用者目錄，所以不必事先知道是 v1-2 還是 v1-3。
不需要 FreeCAD 正在執行，也不需要管理員權限（Windows 用 junction，其他平台用 symlink）。
"""

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

MODULE_NAME = "Agent"  # FreeCAD 認的資料夾名字，不能改
MCP_NAME = "agentcad"
REPO = Path(__file__).resolve().parent


# --- 找 FreeCAD 的使用者目錄 -------------------------------------------


def _candidate_roots():
    """FreeCAD 使用者目錄的可能位置，依平台給。"""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "FreeCAD"] if appdata else []
    if system == "Darwin":
        return [Path.home() / "Library" / "Preferences" / "FreeCAD"]
    return [
        Path.home() / ".local" / "share" / "FreeCAD",
        Path.home() / ".FreeCAD",  # 1.0 之前的舊位置
    ]


def _version_key(name):
    """把 'v1-12' 轉成 (1, 12) 以便正確排序 —— 字串排序會把 v1-9 排在 v1-12 後面。"""
    try:
        major, minor = name[1:].split("-", 1)
        return (int(major), int(minor))
    except (ValueError, IndexError):
        return (-1, -1)


def find_mod_dir():
    """回傳該裝進去的 Mod 目錄。

    FreeCAD 1.0 起使用者目錄是分版本的（`v1-2/Mod`），舊版才是 `Mod`。
    放錯地方 FreeCAD 不會報錯，只是安靜地不載入 —— 所以這裡挑版本號最大的那個。
    """
    for root in _candidate_roots():
        if not root.is_dir():
            continue
        versioned = sorted(
            (d for d in root.iterdir() if d.is_dir() and _version_key(d.name) > (-1, -1)),
            key=lambda d: _version_key(d.name),
        )
        if versioned:
            return versioned[-1] / "Mod"
        if (root / "Mod").is_dir():
            return root / "Mod"
    return None


# --- 安裝 ---------------------------------------------------------------


def _link(target, source):
    """建立連結；不支援就退回複製。回傳實際用的方式。"""
    if platform.system() == "Windows":
        # junction 不需要開發者模式或管理員權限，symlink 兩者都要。
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(source)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return "junction"
    else:
        try:
            target.symlink_to(source, target_is_directory=True)
            return "symlink"
        except OSError:
            pass
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    return "copy"


def _is_link(path):
    if path.is_symlink():
        return True
    if platform.system() == "Windows" and path.is_dir():
        # junction 的 is_symlink() 是 False，要看 reparse point 屬性。
        # 必須用 lstat：stat() 會跟著 junction 走，拿回來的是目標目錄的屬性，永遠不帶這個旗標。
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return False


def _remove(path):
    if _is_link(path):
        # 只拆連結，不要碰到連結指向的原始碼。
        (os.rmdir if platform.system() == "Windows" else os.unlink)(str(path))
        return
    # 保險絲：萬一連結判斷失手，也絕不能遞迴刪到原始碼本身。
    if path.resolve() == REPO:
        raise RuntimeError(f"{path} 指向這個 repo 本身，拒絕遞迴刪除")
    shutil.rmtree(path)


def install(mod_dir):
    target = mod_dir / MODULE_NAME
    mod_dir.mkdir(parents=True, exist_ok=True)

    if target.exists():
        resolved = target.resolve()
        if resolved == REPO:
            print(f"  已經裝好了：{target}")
            return True
        print(f"  移除既有的 {target}（指向 {resolved}）")
        _remove(target)

    how = _link(target, REPO)
    print(f"  {target}  ({how})")
    return True


# --- MCP 註冊 -----------------------------------------------------------


def register_mcp():
    """用 claude CLI 註冊 MCP server；沒有 CLI 就印出手動指令。"""
    server = REPO / "mcp" / "server.py"
    command = ["claude", "mcp", "add", MCP_NAME, "-s", "user", "--", "uv", "run", "--script", str(server)]

    if shutil.which("claude") is None:
        print("  找不到 claude CLI，請自己跑：")
        print("    " + " ".join(command))
        return False

    subprocess.run(["claude", "mcp", "remove", MCP_NAME, "-s", "user"], capture_output=True)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  註冊失敗：{(result.stderr or result.stdout).strip()}")
        print("  手動指令：" + " ".join(command))
        return False
    print(f"  MCP server '{MCP_NAME}' 已註冊 → {server}")
    return True


# --- 檢查 ---------------------------------------------------------------


def check(mod_dir):
    ok = True

    if mod_dir is None:
        print("  [x] 找不到 FreeCAD 的使用者目錄 —— 先把 FreeCAD 開過一次再回來")
        return False
    print(f"  [v] FreeCAD 模組目錄：{mod_dir}")

    target = mod_dir / MODULE_NAME
    if target.exists() and target.resolve() == REPO:
        print(f"  [v] 已安裝：{target}")
    else:
        print(f"  [x] 尚未安裝（預期 {target}）")
        ok = False

    if shutil.which("uv") is None:
        print("  [x] 找不到 uv —— MCP server 需要它（https://docs.astral.sh/uv/）")
        ok = False
    else:
        print("  [v] uv 可用")

    config = Path.home() / ".claude.json"
    if config.is_file():
        try:
            servers = json.loads(config.read_text(encoding="utf-8")).get("mcpServers") or {}
            if MCP_NAME in servers:
                print(f"  [v] MCP server '{MCP_NAME}' 已註冊")
            else:
                print(f"  [x] MCP server '{MCP_NAME}' 未註冊")
                ok = False
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [!] 讀不到 ~/.claude.json：{exc}")

    # 通道是否活著。FreeCAD 沒開很正常，所以這條不算失敗。
    import socket

    with socket.socket() as probe:
        probe.settimeout(0.5)
        alive = probe.connect_ex(("127.0.0.1", 9875)) == 0
    print(f"  [{'v' if alive else '-'}] AI 通道 127.0.0.1:9875 " + ("已上線" if alive else "沒有回應（FreeCAD 沒開就是這樣）"))
    return ok


def main():
    parser = argparse.ArgumentParser(description="把 AgentCAD 裝進 FreeCAD")
    parser.add_argument("--check", action="store_true", help="只檢查現況")
    parser.add_argument("--uninstall", action="store_true", help="移除")
    parser.add_argument("--no-mcp", action="store_true", help="不要註冊 MCP server")
    args = parser.parse_args()

    mod_dir = find_mod_dir()

    if args.check:
        print("AgentCAD 安裝檢查")
        return 0 if check(mod_dir) else 1

    if mod_dir is None:
        print("找不到 FreeCAD 的使用者目錄。")
        print("先把 FreeCAD 開過一次讓它建好目錄，或確認 FreeCAD 1.0 以上已安裝。")
        return 1

    target = mod_dir / MODULE_NAME

    if args.uninstall:
        print("移除 AgentCAD")
        if target.exists():
            _remove(target)
            print(f"  已移除 {target}")
        else:
            print(f"  {target} 本來就不在")
        if shutil.which("claude"):
            subprocess.run(["claude", "mcp", "remove", MCP_NAME, "-s", "user"], capture_output=True)
            print(f"  MCP server '{MCP_NAME}' 已移除")
        return 0

    print("安裝 AgentCAD")
    install(mod_dir)
    if not args.no_mcp:
        register_mcp()

    print()
    print("裝好了。接下來：")
    print("  1. 重開 FreeCAD —— 工作台會自動切到 AgentCAD，AI 通道開在 127.0.0.1:9875")
    print("  2. 重開 Claude Code 讓它接上 MCP server")
    print("  3. 驗證：python smoke.py（FreeCAD 要開著）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
