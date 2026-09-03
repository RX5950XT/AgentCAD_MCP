# AgentCAD_MCP

把 FreeCAD 變成 AI agent 的 3D 建模引擎。純 Python 的 FreeCAD addon，附一個 MCP server。

**只砍人類介面，不砍功能。** 建模能力全部留在 Python API 給 AI 用；收起來的只是
為手動操作準備的選單、工具列與屬性編輯器。人隨時能按「完整介面」把原本的 FreeCAD 叫回來。

人在 AgentCAD 裡只做兩件事：**看**，和**量**。

---

## 安裝

需要 [FreeCAD](https://www.freecad.org/) 1.0 以上（原版即可，不必自己編譯）、
Python 3.10+、[uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/RX5950XT/AgentCAD_MCP.git
cd AgentCAD_MCP
python install.py
```

`install.py` 會自己找到 FreeCAD 的使用者目錄（不必知道是 `v1-2` 還是 `v1-3`）、
把模組連結進去，並註冊 MCP server。然後重開 FreeCAD 與 Claude Code 就好。

```bash
python install.py --check      # 檢查裝好了沒
python install.py --uninstall  # 移除
python install.py --no-mcp     # 只裝 addon，不碰 MCP 設定
```

<details>
<summary>手動安裝</summary>

模組目錄是**分版本**的 —— FreeCAD 1.2 用 `v1-2/Mod`，不是 `FreeCAD/Mod`
（那是舊版路徑，放進去不會被載入，而且沒有任何錯誤訊息）。
不確定的話在 FreeCAD 的 Python 主控台問 `FreeCAD.getUserAppDataDir()`。

```powershell
# Windows（FreeCAD 1.2）
git clone https://github.com/RX5950XT/AgentCAD_MCP.git "$env:APPDATA\FreeCAD\v1-2\Mod\Agent"
```

```bash
# Linux（FreeCAD 1.2）
git clone https://github.com/RX5950XT/AgentCAD_MCP.git ~/.local/share/FreeCAD/v1-2/Mod/Agent
# macOS
git clone https://github.com/RX5950XT/AgentCAD_MCP.git ~/Library/Preferences/FreeCAD/v1-2/Mod/Agent
```

資料夾名稱必須是 `Agent`。接著註冊 MCP server：

```bash
claude mcp add agentcad -s user -- uv run --script <repo 路徑>/mcp/server.py
```
</details>

## 確認能用

FreeCAD 開著，狀態列右下角的指示燈是綠的（點一下可以開關），然後：

```bash
python smoke.py
```

輸出 `AgentCAD 自我檢查全部通過` 就沒問題。

---

## AI 這一側

MCP server 提供 22 個工具。最常用的幾個：

| 工具 | 做什麼 |
|---|---|
| `scene` | 看目前模型全貌：每個物件的長寬高、體積、位置、可調參數與錯誤狀態 |
| `run_code` | 在 FreeCAD 裡執行 Python，完整 API 權限（Part / PartDesign / Draft / Sketcher / Mesh） |
| `measure` | 智慧量測：一個目標給最有意義的尺寸，兩個目標給距離與夾角 |
| `check_geometry` | 幾何健檢 —— 布林運算後一定要跑，「看起來對但其實是兩塊」是最常見的隱形失敗 |
| `check_interference` | 兩零件是否干涉、重疊多少體積；沒干涉時回報間隙 |
| `mass_properties` | 體積、表面積、重心；給密度就估重量（PLA 約 1.24 g/cm³） |
| `screenshot` | 一次抓多個視角，判斷比例遠比單張準 |
| `export_model` | 匯出 STEP / IGES / BREP / STL / 3MF / OBJ |

`capabilities` 會列出全部工具與說明。

變數會跨次 `run_code` 呼叫保留，可以分段建構模型。

## 人這一側：怎麼量尺寸

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

---

## 架構

| 層 | 位置 | 說明 |
|----|------|------|
| FreeCAD 模組 | `agentcad/` | 工作台、極簡介面、測量面板 |
| 內建 RPC | `agentcad/rpc.py` | FreeCAD 啟動時自動開在 `127.0.0.1:9875`，相容舊 `freecad-mcp` 用戶端 |
| MCP server | `mcp/server.py` | 單檔 PEP 723，`uv run --script` 直接跑，不必安裝 |

人看到的數字與 AI 讀到的數字走同一套 `agentcad/tools.py`，不會各說各話。

## 偏好設定

參數群組 `BaseApp/Preferences/Mod/Agent`：

| 鍵 | 預設 | 說明 |
|----|------|------|
| `AutoStart` | `true` | FreeCAD 啟動時自動打開 AI 通道 |
| `Port` | `9875` | RPC 連接埠 |
| `AllowRemote` | `false` | 只收本機連線；打開才聽 `0.0.0.0` |
| `AllowedIPs` | `127.0.0.1` | `AllowRemote` 為 true 時的白名單（逗號分隔，支援 CIDR） |
| `MinimalUI` | `true` | 極簡介面 |

RPC 預設只收本機連線。要開遠端請自行評估風險 —— 它允許執行任意 Python。

## 授權

LGPL-2.1-or-later，與 FreeCAD 一致。
