# AgentCAD_MCP todo
最後更新：2026-11-19

## 現況（交接）
- 獨立的純 Python FreeCAD addon（原版 FreeCAD 1.2 可跑）+ `mcp/server.py`（PEP 723，`uv run --script`）。安裝與 AI 工具清單見 README.md，開發規範、熱抽換與驗證指令見 CLAUDE.md，踩雷見 `tasks/lessons.md`。
- 2026-09-03 從 FreeCAD fork 的 `src/Mod/Agent/` 拆出（原本只靠 6 行 CMake 複製 `.py`，無 C++ 依賴），之後改名 `AgentCAD` → `AgentCAD_MCP` 並公開，授權 LGPL-2.1。
- 本機已清掉兩份舊 `FreeCADMCP` addon（`%APPDATA%/FreeCAD/Mod/` 與 `v1-1/Mod/`）；若再出現會搶 port 9875。

### 介面設計決策（人只做「看」與「量」）
- 工具列 9 顆：`尺寸 │ 看全部 等角 前 上 右 │ 開啟 匯出 │ 完整介面`。量尺寸是主任務所以放第一；「看全部」不叫「全部顯示」，避免和 FreeCAD 的「顯示全部物件」混淆。
- 「AI 通道」開關放在狀態列指示燈（`_StatusDot.mousePressEvent`），不放工具列：它是唯一會讓產品失效的按鈕，按之前要先看得到開／關狀態。
- 刻意保留：前／上／右（量背面、底面的特定面時正投影比手轉準）、開啟（砍了沒人知道能拖放開檔）、尺寸（面板被關掉時的救援）。
- 狀態列收掉 `toggleBottomPanelsButton`、`notificationArea`；保留游標座標、標註尺寸、滑鼠導覽風格。
- 測量面板：標題顯示 Label；有「整體」（選到面／邊／角時把選取升級成整個物件，因極簡模式下樹狀圖收起）、「複製」（`欄位<TAB>值`，可貼試算表）、「清除」；兩物件時顯示最短距離、夾角、間隙 XYZ、中心距；最小寬度 270px。
- 單位與顯示：體積用 cm³（不用 FreeCAD 預設 ml）；`-0.00` 收成 `0.00`。

### 已修過、要防回歸的 bug
- 布林結果（`Part::Cut` 等 Compound）沒有 `CenterOfMass`：一律走 `serialize.center_of_mass()`，取不到退到 `CenterOfGravity`（`tools.mass_properties` 共用）。
- 非同步任務污染同步佇列、`App.Color` 在 1.2 不存在、背景執行緒碰 `ViewObject`：原版 FreeCADMCP 也有這三個 bug，本 repo 已修，細節見 lessons。
- `install.py --uninstall` 曾把 junction 誤判成真目錄差點刪掉原始碼；`_remove()` 的保險絲（路徑等於 repo 就拒絕遞迴刪除）不要拆。

## 待辦
- [ ] 3D 列印可印性檢查（最小壁厚、懸空面）：刻意延後，等真的需要再加。

## 已知問題／刻意不處理
- `ruff` 只剩 B904（錯誤鏈風格）與 B905（zip strict），非死碼，暫不處理。
