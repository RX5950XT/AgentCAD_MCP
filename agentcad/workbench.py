# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 工作台與指令。

之所以放在 package 裡而不是 InitGui.py：FreeCAD 執行完 InitGui.py 之後會把那份全域
命名空間丟掉，寫在 InitGui.py 模組層級的名字在之後的回呼裡會變成 NameError。
放在真正的模組裡，globals 就活得跟 FreeCAD 一樣久。
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from . import measure_panel, minimal_ui, rpc

TOOLBAR = "AgentCAD"

# FreeCAD 內建指令的名字是為選單寫的：帶助記鍵、措辭冗長，而且工作台啟動後
# 還會被重新翻譯蓋回去。極簡工具列只有文字，所以自己包一層，標籤由我們說了算。
# 欄位：指令代號、工具列標籤、被包住的內建指令、提示、是否需要開啟中的文件。
WRAPPED = [
    # 不叫「全部顯示」：FreeCAD 另有「顯示全部物件」的指令，同名會被當成把隱藏的零件叫回來。
    ("Agent_ViewFit", "看全部", "Std_ViewFitAll", "縮放到剛好看得見整個模型", True),
    ("Agent_ViewIso", "等角", "Std_ViewIsometric", "等角視圖", True),
    ("Agent_ViewFront", "前", "Std_ViewFront", "前視圖", True),
    ("Agent_ViewTop", "上", "Std_ViewTop", "上視圖", True),
    ("Agent_ViewRight", "右", "Std_ViewRight", "右視圖", True),
    ("Agent_Open", "開啟", "Std_Open", "開啟既有的模型檔", False),
    ("Agent_Export", "匯出", "Std_Export", "把選取的模型匯出成 STEP／STL 等格式", True),
]

# 順序照「人在 AgentCAD 到底要做什麼」排：先量尺寸（唯一的主任務），
# 再轉視角（為了量得到），然後拿檔案，最後才是平常不會碰的系統開關。
COMMANDS = [
    "Agent_ToggleMeasure",
    "Separator",
    "Agent_ViewFit",
    "Agent_ViewIso",
    "Agent_ViewFront",
    "Agent_ViewTop",
    "Agent_ViewRight",
    "Separator",
    "Agent_Open",
    "Agent_Export",
    "Separator",
    "Agent_ToggleUI",
]


class Wrapped:
    """轉呼叫 FreeCAD 內建指令，只為了換一個短標籤。"""

    def __init__(self, label, target, tip, needs_document):
        self.label = label
        self.target = target
        self.tip = tip
        self.needs_document = needs_document

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip}

    def Activated(self):
        Gui.runCommand(self.target, 0)

    def IsActive(self):
        return App.ActiveDocument is not None if self.needs_document else True


class ToggleMeasure:
    def GetResources(self):
        return {
            "MenuText": "尺寸",
            "ToolTip": "顯示／隱藏尺寸面板。點模型上的面或邊就會量給你看。",
        }

    def Activated(self):
        measure_panel.toggle()

    def IsActive(self):
        return True


class ToggleUI:
    def GetResources(self):
        return {
            "MenuText": "完整介面",
            "ToolTip": "在極簡模式與完整 FreeCAD 介面之間切換。",
        }

    def Activated(self):
        minimal_ui.toggle()

    def IsActive(self):
        return True


class AgentWorkbench(Gui.Workbench):
    MenuText = "AgentCAD"
    ToolTip = "AI agent 專用的 3D 建模環境"

    def Initialize(self):
        self.appendToolbar(TOOLBAR, COMMANDS)
        self.appendMenu(TOOLBAR, COMMANDS)

    def Activated(self):
        # 工具列要等 FreeCAD 建完才收得掉，所以排到事件迴圈的下一輪。
        QtCore.QTimer.singleShot(0, enter_agent_mode)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def enter_agent_mode():
    try:
        if minimal_ui.is_minimal():
            minimal_ui.apply()
        else:
            minimal_ui.install_status_indicator()
    except Exception as exc:
        App.Console.PrintWarning(f"[AgentCAD] 套用極簡介面失敗：{exc}\n")


def boot():
    """開 AI 通道，並在第一次啟動時把 AgentCAD 設成預設工作台。"""
    try:
        minimal_ui.claim_default_workbench()
        if App.ParamGet(rpc.PARAM_PATH).GetBool("AutoStart", True):
            App.Console.PrintMessage(f"[AgentCAD] {rpc.start()}\n")
    except Exception as exc:
        App.Console.PrintError(f"[AgentCAD] AI 通道啟動失敗：{exc}\n")


def register():
    for name, label, target, tip, needs_document in WRAPPED:
        Gui.addCommand(name, Wrapped(label, target, tip, needs_document))
    Gui.addCommand("Agent_ToggleMeasure", ToggleMeasure())
    Gui.addCommand("Agent_ToggleUI", ToggleUI())
    Gui.addWorkbench(AgentWorkbench())
    QtCore.QTimer.singleShot(0, boot)
