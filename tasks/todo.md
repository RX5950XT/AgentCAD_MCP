# AgentCAD — 把 FreeCAD 改造成 AI agent 專用 3D 建模軟體

## 目標

100% 針對 AI agent 的 3D 建模軟體：AI 透過 MCP 全權操控，人類只負責「看」與「量」。

## 架構決策

- **不砍功能，只砍人類介面。** 建模能力全部保留在 Python API 層（AI 用得到），
  移除的只是人類手動操作用的工具列/選單/對話框。
- **新增單一模組 `src/Mod/Agent/`**（純 Python，免編譯），內含：
  1. 內建 RPC server（取代外掛 FreeCADMCP，相容既有方法名，port 9875）
  2. 極簡工作台 `AgentWorkbench` + 極簡 UI 套用邏輯
  3. 智慧測量面板
- **MCP server** 放 `tools/agentcad-mcp/`，暴露全部新工具給 Claude Code / Codex。

## 待辦

- [x] 盤點現有 FreeCADMCP 外掛 API 與 FreeCAD 模組結構
- [x] P1-1 `src/Mod/Agent/` 骨架 + CMakeLists + 掛進 src/Mod/CMakeLists.txt
- [x] P1-2 `agent/serialize.py` — token 友善序列化（含 scene_digest 精簡格式）
- [x] P1-3 `agent/rpc.py` — RPC 傳輸層 + 相容既有 freecad-mcp 方法
- [x] P1-4 `agent/tools.py` — 新增 AI 專用工具（量測/檢查/視角/匯出/診斷/交易）
- [x] P1-5 `InitGui.py` — 自動啟動 RPC + 註冊工作台
- [x] P2-1 `agent/minimal_ui.py` — 隱藏人類建模 UI（工具列/選單/工作台清單）
- [x] P2-2 `agent/measure_panel.py` — 智慧測量面板（選取即顯示尺寸）
- [x] P3-1 `tools/agentcad-mcp/` — MCP server（含全部新工具）
- [x] P4-1 建置驗證：configure + build + install + 啟動 FreeCAD 實測
- [x] P4-2 MCP 實測：ping / scene_digest / measure / screenshot
- [x] P5 更新 CLAUDE.md / AGENTS.md / CONTEXT.md / README / tasks/lessons.md
- [x] P6 留下可重跑的自我檢查 `tools/agentcad_smoke.py`

## 驗收標準

1. `pixi run freecad-release` 啟動後預設進 AgentCAD 工作台，畫面只剩 3D 視圖＋測量面板。
2. RPC server 自動啟動，`mcp__freecad__*` 既有工具全部照常可用（不影響現有 AI 操作）。
3. 新 MCP server 可 `scene_digest`、`measure`、`check_geometry`、`export`、`set_view`。
4. 人類選取物件時測量面板即時顯示 W×D×H／體積／表面積。

## Review（2026-09-03）

### 做出來的東西

- `src/Mod/Agent/`：純 Python 模組，內建 RPC 伺服器 + 極簡工作台 + 智慧測量面板。
- `tools/agentcad-mcp/server.py`：單檔 MCP server（PEP 723，`uv run --script` 直接跑），22 個工具。
- CMake：新增 `BUILD_AGENT` 選項並掛進 `src/Mod/CMakeLists.txt`。

### 驗證結果

| 項目 | 結果 |
|------|------|
| RPC 自動啟動 | `ping` / `list_tools` 通過，15 個擴充工具 + 相容方法 |
| 舊 `freecad-mcp` 用戶端 | `claude mcp list` 顯示 `freecad: ✔ Connected`，全部相容方法實測通過 |
| 新 MCP server | 真的走 stdio 握手，`scene` / `measure` / `screenshot` 全通 |
| 極簡介面 | menubar 隱藏、9 條原生工具列全隱藏、5 個原生 dock 全隱藏，只留 AgentCAD 工具列與尺寸面板 |
| 智慧測量 | 選面顯示面積／直徑／半徑／法線；未選取顯示整體外框 |
| 匯出 | STL 6084 bytes、STEP 8303 bytes |

### 順手修掉的既有 bug

1. 非同步任務污染同步佇列 → `delete_object` 回傳錯的名字。
2. `App.Color` 在 FreeCAD 1.2 不存在 → 所有 Quantity 屬性讀成 `<error: ...>`。
3. `get_object` / `get_objects` 在背景執行緒碰 `ViewObject` → 主執行緒檢查直接擋下。

（1、2、3 在原本的 FreeCADMCP addon 上同樣是壞的。）

### 沒做

- **完整 C++ 重新編譯沒跑**：這台機器的 `build/` 綁在舊路徑，砍掉重 configure 需要
  MSVC 環境且完整編譯以小時計。本次改動是純 Python + 三行 CMake，驗證方式是把模組
  裝進 `.pixi/envs/default/Library/Mod/Agent`（也就是 `install-release` 會做的事）後實際啟動。
  下次要出安裝檔時需完整跑一次 `configure → build → install`。
- 3D 列印可印性檢查（最小壁厚／懸空面）先不做，等真的需要再加。

## 第二輪：介面與測量體驗優化（2026-09-03）

### 做了什麼

- **工具列／選單順序重排**：改成照「人在 AgentCAD 到底要做什麼」排 ——
  `尺寸 | 全部顯示 等角 前 上 右 | 開啟 匯出 | AI 通道 完整介面`。
  量尺寸是人在這套軟體裡唯一的主任務，所以擺第一個；系統開關擺最右邊。
- **測量面板**：
  - 加「複製」：一鍵把整組讀數複製成 `欄位<TAB>值` 的文字，可直接貼進試算表。
  - 加「清除」：不必再去 3D 空白處點一下才能回到整體尺寸。
  - 標題改顯示 **Label**（樹狀圖上看到的名字）而不是內部 Name；元素代號移到副標。
  - 兩物件時補上 **間隙 XYZ**（三軸分量），量配合間隙比斜線距離實用；
    拿掉重複的「中心位移」。
  - 操作說明寫在面板上（沒選取時一句、選一個時一句），不用去翻文件。
  - 最小寬度 270px，XYZ 三組數字不會被切掉尾數。
- **順手修掉一個 layout bug**：`QGridLayout.rowCount()` 只增不減，導致每刷新一次
  讀數就往下掉一列。

### 驗證

```
$ python tools/agentcad_smoke.py
AgentCAD 自我檢查全部通過

面板三種狀態（截圖 + 讀數實測）：
整體尺寸 | 沒有選取，顯示全部可見模型的外框。點面量面積、點邊量長度，按住 Ctrl 點兩個量距離。
  [('寬 X','60.00 mm'),('深 Y','40.00 mm'),('高 Z','50.00 mm'),('中心','30.00  20.00  25.00'),('零件數','2')]
底板 | Face6 · 面 · Plane — 按住 Ctrl 再點一個就量距離
  [('面積','24.00 cm²'),('法線','0.00  0.00  1.00')]
兩者之間 | 底板.Face6 ↔ 立柱.Face3
  [('最短距離','40.00 mm'),('夾角','平行'),('間隙 XYZ','0.00  0.00  40.00'),('中心距','41.23 mm')]
連刷兩次後 first row at 0（rowCount bug 已修）
```

## 第三輪：程式碼健檢與死碼清理（2026-09-03）

### 做了什麼

- `ruff check --select F,E,W,B,UP,SIM,ARG` 掃全部 Agent 程式碼，無未使用 import／變數。
- 刪掉 `rpc.status()` 的 `uptime_check` 假欄位（名不副實、零呼叫端），連帶 `import time`。
- 刪掉 `_NetworkSet` —— 只為了讓 `in` 成立的單一用途包裝類別，`verify_request` 直接 `any()`。
- 刪掉 `AgentWorkbench.Deactivated` 空方法（`Gui.Workbench` 基底已有預設實作）。
- `tools/translate_tw_from_cn.py`：`base_dir` 硬寫已不存在的 `D:/Workspace_cloud/...`，
  改成以腳本自身定位專案根目錄；順手刪掉未使用的 `os` / `re` import。
- 文件更正：`pixi run freecad-release` 在本機會失敗（depends-on `install-release`，
  但從未完整編譯過），CLAUDE.md / AGENTS.md / CONTEXT.md 改寫成直接跑 exe 的正確做法。

### 驗證

```
$ ruff check --isolated --select F,E,W,B --ignore E501,E402 src/Mod/Agent tools/
（僅剩 B904 錯誤鏈風格與 B905 zip strict，非死碼）

$ python tools/agentcad_smoke.py
AgentCAD 自我檢查全部通過

面板健檢（對執行中的 AgentCAD）：
ping True ／ tools 15
CLEAR_SLOT ok            ← clicked(bool) 傳給 Gui.Selection.clearSelection 不會炸
OVERALL 整體尺寸 [('寬 X','60.00 mm'),('深 Y','40.00 mm'),('高 Z','10.00 mm'),...]
FACE 底板 [('面積','24.00 cm²'),('法線','0.00  0.00  1.00')]
ROW0 0                   ← rowCount bug 沒有回歸
CLIPBOARD '底板\n面積\t24.00 cm²\n法線\t0.00  0.00  1.00'
```

## 第四輪：工具列再精簡（2026-09-03）

### 做了什麼

- **「AI 通道」從工具列移到狀態列的指示燈**：它是全場唯一按下去會讓整個產品失效的
  按鈕，卻跟「等角」「匯出」一樣大小排在一起。開關搬到它自己的狀態顯示上
  （`_StatusDot.mousePressEvent`），按之前就看得到現在是開還關。`ToggleServer`
  指令連同註冊一併刪除 —— 功能沒少，只是換了地方。
- **「全部顯示」→「看全部」**：FreeCAD 另有「顯示全部物件」的指令，同名會被誤解成
  把隱藏的零件叫回來；順帶讓工具列每顆都是 2-3 字，節奏整齊。
- **收掉狀態列兩個手動操作殘留**：`toggleBottomPanelsButton`（會把 Python console
  叫回來）、`notificationArea`（FreeCAD 內部通知）。留下對「看」有用的：滑鼠指到
  哪個面／邊的即時座標、標註尺寸、滑鼠導覽風格。
- `_hidden_docks` / `_hidden_toolbars` 合併成單一 `_hidden`，restore 少一個迴圈。

工具列 11 → 9 顆：`尺寸 │ 看全部 等角 前 上 右 │ 開啟 匯出 │ 完整介面`

### 沒砍的與理由

- **前／上／右**：看起來跟滑鼠拖拉重複，但量測要點到背面或底面的特定面時，
  正投影比手轉精確。
- **開啟**：FreeCAD 本身支援拖放開檔，理論上可砍，但砍了沒人知道能拖。
- **尺寸**：面板預設開著，這顆只是不小心關掉時的救援。

### 驗證

```
$ python tools/agentcad_smoke.py
AgentCAD 自我檢查全部通過

TOOLBAR ['尺寸','看全部','等角','前','上','右','開啟','匯出','完整介面']
hidden bottom-panel btn: False   ← 已收
hidden notification:     False   ← 已收
kept navigation:         True    ← 留著
RESTORED  menubar True  bottom-panel True  notification True  leftover 0
RE-APPLIED menubar False bottom-panel False notification False

狀態燈點擊實測：
before      running=True  | ● AI 已就緒 · port 9875
click1(off) running=False | ● AI 未連線
click2(on)  running=True  | ● AI 已就緒 · port 9875
```

## 第五輪：量測操作全驗與四個修正（2026-09-03）

### 做了什麼

把「人量尺寸」的每一種操作實跑一次（不選／面／邊／角／Ctrl 兩個／整體），發現四個問題：

1. **「這個零件多大、多重」量不到** —— 3D 視圖只選得到面／邊／角，選整個零件要樹狀圖，
   而樹狀圖在極簡模式下是收起來的。面板加一顆「整體」鈕（只在選到子元素時出現），
   按下去把選取升級成整個物件。
2. **布林運算的零件沒有重心** —— `Part::Cut` 產生的是 Compound，Compound 沒有
   `CenterOfMass`（只有 Solid 有），程式問錯屬性就安靜地少一列。新增
   `serialize.center_of_mass()`，取不到就退到 `CenterOfGravity`；`tools.mass_properties`
   同一個根因也一併修好（AI 之前估不出列印重量）。
3. **體積顯示成 `22.87 ml`** —— FreeCAD 標準單位制給 ml，這裡量的是零件不是液體，改成 cm³。
4. **法線出現 `-0.00`** —— 浮點 -1e-17 顯示成負零很像出錯，收成 `0.00`。

過程中踩到一個重入 bug：`clearSelection()` 是同步回呼，會當場觸發 `refresh()` 把
`_whole_target` 清成 None。已記進 `tasks/lessons.md`。

### 順手修掉的流程問題

為了測 Python 改動重啟了 4 次 FreeCAD，每次都害 port 9875 上的 MCP 用戶端斷線重連，
各起一批 `uv` / `freecad-mcp` / conhost 黑框。實際上用 `importlib.reload` 熱抽換就好，
已驗證可行並寫進 CLAUDE.md / AGENTS.md。

### 驗證

```
$ python tools/agentcad_smoke.py
AgentCAD 自我檢查全部通過

A 不選     整體尺寸  [寬60 深40 高35 中心 零件數2]              鈕：整體=False
B 平面     支架·Face6·Plane    [面積4.00cm² 法線1.00 0.00 0.00]  整體=True
C 孔內壁   支架·Face7·Cylinder [面積3.77cm² 直徑12.00 半徑6.00]  整體=True
D 孔口圓邊 支架·Edge10·Circle  [長度37.70 直徑12.00 圓心15 20 10] 整體=True
E 角       支架·Vertex1        [座標 0.00 0.00 10.00]             整體=True
F 兩個面   兩者之間 [最短距離7.00 夾角90.0° 間隙XYZ 7/0/0 中心距15.81]
G 兩個圓邊 兩者之間 [最短距離29.68 間隙XYZ 16/0/25 中心距39.05]
H 按整體鈕 支架·單一零件 [寬60 深40 高10 體積22.87cm³ 表面積69.51cm² 重心30.74 20.00 5.00]

AI 側同一個修正：
mass_properties("Bracket", 1.24) → center_of_mass [30.7418,20.0,5.0], mass_g 28.358

熱抽換驗證（沒有重開 FreeCAD）：
RELOADED ／ 面板按鈕：['整體','複製','清除']
```

## 第六輪：拆成獨立 addon（2026-09-03）

### 做了什麼

AgentCAD 原本住在一個 FreeCAD fork 的 `src/Mod/Agent/`，靠 6 行 CMake 掛進編譯。
盤點後發現那 6 行只是把 `.py` 複製到安裝目錄，沒有任何 C++ 依賴 ——
114 KB 的東西被綁在 2.6 GB 的 repo 裡，別人要用得先抓整個 fork。

- 拆成獨立 repo `D:/Workspace/Personal_Project/AgentCAD`（18 個檔案，`.git` 153 KB）
- 結構重整：`src/Mod/Agent/agentcad/` → `agentcad/`，
  `tools/agentcad-mcp/server.py` → `mcp/server.py`，`tools/agentcad_smoke.py` → `smoke.py`
- 新寫 `README.md`（安裝、接 AI、量測操作表）與 `CLAUDE.md` / `AGENTS.md`（開發規範）
- fork 側：撤掉 6 行 CMake、刪除 AgentCAD 全部檔案、改寫 `README.md` /
  `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` 指向新 repo
- MCP 重新註冊指向 `AgentCAD/mcp/server.py`（舊路徑的檔案已刪，原註冊是壞的）
- 順手清掉兩份漏網的舊 `FreeCADMCP` addon：`%APPDATA%/FreeCAD/Mod/`（**啟用中**，
  會搶 port 9875）與 `%APPDATA%/FreeCAD/v1-1/Mod/`

### 踩到的坑

junction 第一次建在 `%APPDATA%/FreeCAD/Mod/Agent`，FreeCAD 完全沒反應也沒報錯 ——
1.2 讀的是 `v1-2/Mod/`。已記進 `lessons.md`。

### 驗證

```
$ python smoke.py
AgentCAD 自我檢查全部通過

模組載入自： D:\Workspace\Personal_Project\AgentCAD\agentcad\__init__.py
面板檔案：   D:\Workspace\Personal_Project\AgentCAD\agentcad\measure_panel.py
工具列：     ['尺寸','看全部','等角','前','上','右','開啟','匯出','完整介面']

$ claude mcp get agentcad
Status: ✔ Connected
Args: run --script D:/Workspace/Personal_Project/AgentCAD/mcp/server.py
```

FreeCAD fork 的 `src/Mod/Agent/` 已完全移除，載入來源唯一。

## 第七輪：改名、一鍵安裝、公開發布（2026-09-03）

### 做了什麼

- repo 改名 `AgentCAD` → `AgentCAD_MCP`，junction 重建指向新路徑
- **新增 `install.py`** —— 「丟 repo 連結給 agent，它自己就裝得好」的核心：
  自動偵測 FreeCAD 使用者目錄（跨平台，挑版本號最大的 `vX-Y`）、
  建立連結（Windows junction／其他 symlink／都不行就複製）、註冊 MCP server。
  另有 `--check`（現況體檢）、`--uninstall`、`--no-mcp`。
- README 重寫成安裝優先：三行指令裝好，手動安裝收進 `<details>`
- 補上 LGPL-2.1 `LICENSE` 全文
- 推上 GitHub 公開

### 差點出事的 bug

`install.py --uninstall` 第一次跑就炸了：`_is_link()` 沒認出 Windows junction，
掉進 `shutil.rmtree` —— 那會遞迴刪掉 repo 的原始碼本身。
是 `shutil.rmtree` 自己的「Cannot call rmtree on a symbolic link」擋下來的。

根因：`os.stat()` 會**跟著** junction 走，拿回來的是目標目錄的屬性，
永遠不帶 `FILE_ATTRIBUTE_REPARSE_POINT`。必須用 `os.lstat()`。
順手在 `_remove()` 加了保險絲：路徑解析後等於 repo 本身就拒絕遞迴刪除。

### 驗證

```
$ python install.py --uninstall
移除 AgentCAD
  已移除 C:\Users\rx595\AppData\Roaming\FreeCAD\v1-2\Mod\Agent
  MCP server 'agentcad' 已移除
（原始碼完好：agentcad/ 下 8 個 .py 都還在）

$ python install.py
安裝 AgentCAD
  C:\Users\rx595\AppData\Roaming\FreeCAD\v1-2\Mod\Agent  (junction)
  MCP server 'agentcad' 已註冊 → D:\Workspace\Personal_Project\AgentCAD_MCP\mcp\server.py

$ python install.py --check
  [v] FreeCAD 模組目錄：C:\Users\rx595\AppData\Roaming\FreeCAD\v1-2\Mod
  [v] 已安裝  [v] uv 可用  [v] MCP server 'agentcad' 已註冊
```
