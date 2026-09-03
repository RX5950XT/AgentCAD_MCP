# AgentCAD 開發規範

把 FreeCAD 變成 AI agent 的 3D 建模引擎。純 Python 的 FreeCAD addon，不需要編譯 FreeCAD。

安裝、使用方式與量測操作看 `README.md`。這份只寫「改這個 repo 的人要知道的事」。

## 核心原則

**只砍人類介面，不砍功能。** 建模能力全部留在 Python API 給 AI 用；
收起來的只是手動操作用的選單／工具列／屬性編輯器。人隨時能按「完整介面」叫回原本的 FreeCAD。

人在 AgentCAD 裡只做兩件事：看、量。任何新按鈕都要先過這一關。

## 慣例

- **新增 AI 工具**：在 `agentcad/tools.py` 加一個公開函式即可，`rpc.py` 會自動註冊成 RPC 方法；
  回傳值必須可 JSON 化（`Base.Quantity` 要先轉 float）。要讓 MCP 用戶端看到，再到
  `mcp/server.py` 加薄包裝。
- **碰 GUI 一律排到主執行緒**：FreeCAD 1.2 起 GUI API 只准主執行緒用，
  連序列化都算（會讀 `ViewObject`）。用 `rpc.on_gui()`。
- **邏輯不要寫在 `InitGui.py`**：FreeCAD 執行完就丟掉那份 globals，之後的回呼會 NameError。
  `InitGui.py` 只負責 `workbench.register()`。
- 人看到的數字與 AI 讀到的數字走同一套 `agentcad/tools.py`，不要各寫一份。

## 開發流程

這個 repo 就是 FreeCAD 的模組目錄本身（clone 到 `%APPDATA%\FreeCAD\Mod\Agent`），
所以改完 `.py` 不用複製，但要讓執行中的 FreeCAD 重新載入。

### 改完 Python 不要重開 FreeCAD

重啟一次 FreeCAD，掛在 port 9875 上的 MCP 用戶端就會斷線重連，
每次都多開一批 `uv` / `freecad-mcp` / conhost 黑框，工作列很快就爆掉。
透過 AI 通道熱抽換就好：

```python
import importlib
import FreeCADGui as Gui
from PySide import QtWidgets
from agentcad import measure_panel

main = Gui.getMainWindow()
dock = main.findChild(QtWidgets.QDockWidget, measure_panel.PANEL_NAME + "_Dock")
if dock is not None:
    if measure_panel._watcher is not None:
        Gui.Selection.removeObserver(measure_panel._watcher)
    dock.setParent(None)
    dock.deleteLater()

for name in ("serialize", "tools", "measure_panel", "minimal_ui", "workbench"):
    importlib.reload(importlib.import_module("agentcad." + name))

from agentcad import measure_panel as fresh
fresh.show()
```

**一個例外**：`rpc.py` 在啟動時就把 `tools.py` 的函式物件綁進 XML-RPC 伺服器了，
所以改 `tools.py` 的函式內容，面板會立刻更新（它走屬性查找），
但 AI 那側的 RPC 方法還是舊的 —— 那種改動才需要重開。

### 驗證

改完一定要跑：

```bash
python smoke.py          # AI 通道與工具算得對不對
ruff check --isolated --select F,E,W,B --ignore E501,E402 .
```

宣告完成前必附驗證指令與實際輸出；沒跑過就不算完成。

## 兩個容易踩的坑

1. **FreeCAD 執行完 `InitGui.py` 會丟掉它的全域命名空間。** 寫在 `InitGui.py` 模組層級的
   名字，在工作台方法或 `QTimer` 回呼裡會變成 `NameError`。所以邏輯一律放 package 裡。
2. **FreeCAD 1.2 起 GUI API 只准在主執行緒用。** RPC 在背景執行緒收請求，任何碰到
   `ViewObject`／3D 視圖的動作都必須經由 `rpc.on_gui()` 排到主執行緒。

其餘踩過的坑記在 `tasks/lessons.md`，動手前先讀一遍。

## 安全底線

- 不可硬編碼 secrets；一律用環境變數。
- RPC 預設只收本機連線（`127.0.0.0/8`）。要開遠端必須自己在偏好設定打開，
  並設白名單 —— 這條防線不要為了方便拆掉。
- 錯誤訊息不得洩漏敏感資訊。
- 所有外部輸入都要驗證：RPC 參數、檔案內容、AI 送來的程式碼路徑。

## 與 FreeCAD 本體的關係

這個 repo 不依賴任何 FreeCAD fork，只用標準 API（`FreeCAD`、`FreeCADGui`、`PySide`、
`Part`、`Mesh`）。原版 FreeCAD 1.2 就能跑。

歷史：2026-09-03 之前住在一個 FreeCAD fork 的 `src/Mod/Agent/` 裡，
靠 6 行 CMake 掛進編譯。那 6 行只是把 `.py` 複製到安裝目錄，沒有任何 C++ 依賴，
所以拆成獨立 addon 沒有損失。那個 fork 現在只負責繁體中文化與 QSS 改造。
