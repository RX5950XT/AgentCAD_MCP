# 教訓紀錄

## FreeCAD

### InitGui.py 的全域命名空間會被丟掉
**現象**：工作台的 `Initialize()` / `Activated()` 或 `QTimer` 回呼裡出現 `NameError`，
但同樣的名字明明寫在 `InitGui.py` 模組層級。
**原因**：FreeCAD 執行完 `InitGui.py` 之後不保留那份 globals。
**做法**：`InitGui.py` 只做 `from <package> import workbench; workbench.register()`，
所有類別、常數、函式一律住在真正的 package 模組裡。

### FreeCAD 1.2 起 GUI API 只准主執行緒
**現象**：`RuntimeError: GUI API 'FreeCADGui.getDocument' may only be used from the main thread`。
**原因**：背景執行緒（例如 RPC handler）碰到 `ViewObject` 或 3D 視圖。
**做法**：連「看起來唯讀」的序列化都要排到主執行緒，因為它會讀 `ViewObject`。

### API 名稱在 1.2 有變動
- `ParameterGrp.SetASCII` → `SetString`
- `FreeCAD.Color` 不存在了；直接 `isinstance(v, App.Color)` 會 AttributeError，
  而且那個例外會讓同一個 try 區塊裡的每個屬性都變成 `<error: ...>`。
- `App::PropertyLength` 回傳的是 `Base.Quantity`，不是 float，XML-RPC 送不出去。

### 只有一組 request/response 佇列時，非同步任務會污染同步呼叫
**現象**：`delete_object` 回傳 `object_name: None`，但實際刪除成功。
**原因**：`execute_code_async` 的回傳值被塞進共用的 `_results`，下一個同步呼叫讀到它。
**做法**：佇列元素帶上「要不要回結果」旗標，非同步的不回。

### 工具列標籤搶不贏 FreeCAD 的重新翻譯
**現象**：在工作台 `Activated()` 裡 `action.setText()` 會被蓋回內建的
「適應所有(&F)」。
**做法**：不要跟它搶時序。自己做一個薄指令包住 `Std_*`，標籤就完全由自己決定。

## 本機環境

- `build/` 的 CMakeCache 綁死絕對路徑；專案搬過目錄就必須整個刪掉重 configure。
- `pixi run <exe>` 不會設定 Qt plugin 路徑，會噴
  `Could not find the Qt platform plugin "windows"`；要自己給
  `QT_QPA_PLATFORM_PLUGIN_PATH=.pixi/envs/default/Library/lib/qt6/plugins/platforms`。
- FreeCAD 使用者目錄是 `%APPDATA%\FreeCAD\v1-2\`，不是 `%APPDATA%\FreeCAD\`。
- 停用 addon 不能只改資料夾名字 —— 只要目錄裡有 `Init.py`／`InitGui.py`，FreeCAD 照載不誤。
  要整個移出 `Mod/`。

### QGridLayout 的 rowCount() 移除項目後不會縮回
**現象**：測量面板每刷新一次，讀數就往下掉一列，上方留下越來越大的空白。
**原因**：`takeAt()` 把項目移出佇列，但 `rowCount()` 記的是歷史最高列數，只增不減。
**做法**：自己數列號（`row = len(self._readout)`），不要問 layout。
另外清空時要 `setParent(None)` 再 `deleteLater()`，否則舊 label 會一路畫到事件迴圈有空為止。

### Gui.Selection.clearSelection() 會當場回呼，不是排隊
**現象**：面板「整體」鈕按下去噴 `addSelection() argument after * must be an iterable, not NoneType`。
**原因**：`clearSelection()` 同步觸發 `_SelectionWatcher.clearSelection` → `panel.refresh()`，
而 `refresh()` 開頭會把 `_whole_target` 重設成 None —— 等於自己把手上的東西清掉了才要用。
**做法**：任何「先清選取、再重選」的動作，都要先把目標抓進區域變數再呼叫 `clearSelection()`。
FreeCAD 的 Selection observer 是同步回呼，不要當成事件佇列。

### FreeCAD 的使用者模組目錄是分版本的
**現象**：addon 放進去，FreeCAD 完全沒反應 —— 工作台沒出現、RPC 沒開、也沒有任何錯誤訊息。
**原因**：FreeCAD 1.2 讀的是使用者目錄下的 `v1-2/Mod/`，不是 `Mod/`。
`Mod/` 是舊版路徑，東西放那裡只會安靜地被忽略。
**做法**：裝 addon 前先在 Python 主控台問 `FreeCAD.getUserAppDataDir()`，
路徑是 `<那個目錄>/Mod/<AddonName>`。同一台機器可能同時存在 `Mod/`、`v1-1/Mod/`、
`v1-2/Mod/` 三份，舊版留下的東西要一起清。

### FreeCAD 1.2 的 Part 基本形狀沒有 mustExecute()
**現象**：`problems`／`recompute` 一律回錯，`AttributeError: 'PrimitivePy' object has no attribute 'mustExecute'`。
**原因**：FreeCAD 1.2 把 `Part::Box` 這類基本形狀改成 Python 實作（`PrimitivePy`），
沒有 C++ DocumentObject 的 `mustExecute()`。文件裡只要有一個基本形狀，整份就掃不完。
**做法**：判斷待重算改看狀態旗標 `"Touched" in obj.State`，所有物件型別通用。
FreeCAD 1.2 起別再假設 `DocumentObject` 的 C++ 方法都還在。

### 不要對執行中的 rpc.py 做 importlib.reload
**現象**：reload 之後 RPC 還通，但 `run_code` 的 `Output:` 永遠空白，
`scene` 之類的呼叫甚至回傳上一個請求的結果（拿到 `true`）。
**原因**：reload 重跑模組本體，`_requests`／`_results` 換成全新的 Queue，
但已排隊的舊結果與舊 QTimer pump 鏈還在，request 與 result 從此錯開一格。
`_server`／`_thread` 也被重設成 None，`stop()` 就再也關不掉伺服器。
**做法**：`rpc.py` 改完就重開 FreeCAD，只有 `serialize`／`tools`／面板那幾個模組能熱抽換。
