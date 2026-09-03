# AgentCAD

把 FreeCAD 變成 AI agent 的 3D 建模引擎。純 Python，不需要編譯 FreeCAD。

**只砍人類介面，不砍功能。** 建模能力全部留在 Python API 給 AI 用；收起來的只是
為手動操作準備的選單、工具列與屬性編輯器。人隨時能按「完整介面」把原本的 FreeCAD 叫回來。

人在 AgentCAD 裡只做兩件事：**看**，和**量**。

## 安裝

需要 FreeCAD 1.2 或更新的版本（原版即可，不必自己編譯）。

把這個 repo 放進 FreeCAD 的模組目錄，資料夾名稱必須是 `Agent`：

```powershell
# Windows
git clone <repo-url> "$env:APPDATA\FreeCAD\Mod\Agent"
```

```bash
# Linux / macOS
git clone <repo-url> ~/.local/share/FreeCAD/Mod/Agent
```

重開 FreeCAD，工作台選單裡就會出現 AgentCAD，AI 通道自動開在 `127.0.0.1:9875`。

## 接上 AI

MCP server 是單檔 PEP 723 腳本，`uv` 會自己處理相依，不需要先安裝：

```bash
claude mcp add agentcad -s user -- uv run --script <這個 repo>/mcp/server.py
```

Codex 或其他 MCP 用戶端同理，指向同一個 `mcp/server.py`。

AgentCAD 視窗要開著，而且狀態列右下角的指示燈是綠的（點一下可以開關）。

## 確認能用

```bash
python smoke.py
```

輸出 `AgentCAD 自我檢查全部通過` 就沒問題。

## 人怎麼量尺寸

| 你做的事 | 面板給你 |
|---|---|
| 什麼都不點 | 整體尺寸：寬深高、中心、零件數 |
| 點一個**面** | 面積；圓柱面另給直徑、半徑；加法線方向 |
| 點一個**邊** | 長度；圓弧另給直徑、半徑、圓心；直線給起點終點 |
| 點一個**角** | 座標 |
| **Ctrl** 點兩個 | 最短距離、夾角、間隙 XYZ、中心距 |
| 按**「整體」** | 這個零件的寬深高、體積、表面積、重心 |
| 按**「複製」** | 讀數變文字進剪貼簿（Tab 分隔，直接貼 Excel） |
| 按**「清除」** | 回到整體尺寸 |
| 滑鼠**移過去不用點** | 狀態列左下角即時顯示是哪個面／邊 + 座標 |

常見量法：**孔徑**點孔內壁或孔口圓邊；**壁厚**Ctrl 點內外兩個面看最短距離；
**兩孔中心距**Ctrl 點兩個孔口圓邊看中心距；**配合間隙**看「間隙 XYZ」而不是最短距離
（斜線距離對不上組裝方向）。

## 架構

| 層 | 位置 | 說明 |
|----|------|------|
| FreeCAD 模組 | `agentcad/` | 工作台、極簡介面、測量面板、RPC 伺服器 |
| 內建 RPC | `agentcad/rpc.py` | FreeCAD 啟動時自動開在 `127.0.0.1:9875`，相容舊 `freecad-mcp` 用戶端 |
| MCP server | `mcp/server.py` | 單檔 PEP 723，22 個工具，`uv run --script` 直接跑 |

人看到的數字與 AI 讀到的數字走同一套 `agentcad/tools.py`，不會各說各話。

## 偏好設定

參數群組 `BaseApp/Preferences/Mod/Agent`：

| 鍵 | 預設 | 說明 |
|----|------|------|
| `AutoStart` | `true` | FreeCAD 啟動時自動打開 AI 通道 |
| `Port` | `9875` | RPC 連接埠（與舊 `freecad-mcp` 相同） |
| `AllowRemote` | `false` | 只收本機連線；打開才聽 `0.0.0.0` |
| `AllowedIPs` | `127.0.0.1` | `AllowRemote` 為 true 時的白名單（逗號分隔，支援 CIDR） |
| `MinimalUI` | `true` | 極簡介面 |

## 授權

LGPL-2.1-or-later，與 FreeCAD 一致。
