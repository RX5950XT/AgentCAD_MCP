# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 極簡介面。

想法很簡單：**3D 模型是唯一的主角**。AI 負責建模，人只負責看。
所以把 FreeCAD 為手動建模準備的選單列、工具列、屬性編輯器全部收起來，
只留 3D 視圖、一條看視角用的工具列、一個尺寸面板、一個 AI 連線指示。

功能沒有被拿掉，只是不再擺在人面前 —— AI 透過 Python API 依然拿得到全部能力，
人也隨時能用「完整介面」把原本的 FreeCAD 叫回來。
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import measure_panel, rpc

# 這幾個 dock 是 AgentCAD 自己的，不能收。
KEEP_DOCKS = frozenset([measure_panel.PANEL_NAME + "_Dock"])
# 只留這條工具列：切視角、量測、AI 狀態。
KEEP_TOOLBARS = frozenset(["AgentCAD"])
# 狀態列上這兩個是手動操作的殘留：一個把 Python console 叫回來，一個是 FreeCAD 內部通知。
# 留在畫面上的是對「看」有用的：滑鼠指到哪個面／邊、視圖尺寸、滑鼠導覽風格。
HIDE_STATUS_WIDGETS = frozenset(["toggleBottomPanelsButton", "notificationArea"])

_hidden = []  # 極簡模式收起來的 widget，restore() 時原樣叫回來
_menubar_hidden = False
_status_label = None


def _main():
    return Gui.getMainWindow()


def is_minimal():
    return App.ParamGet(rpc.PARAM_PATH).GetBool("MinimalUI", True)


def set_minimal(enabled):
    App.ParamGet(rpc.PARAM_PATH).SetBool("MinimalUI", bool(enabled))


def apply():
    """收起所有人類手動建模用的介面。"""
    global _menubar_hidden
    main = _main()
    if main is None:
        return

    for dock in main.findChildren(QtWidgets.QDockWidget):
        if dock.objectName() in KEEP_DOCKS or not dock.isVisible():
            continue
        dock.hide()
        _hidden.append(dock)

    for bar in main.findChildren(QtWidgets.QToolBar):
        if bar.objectName() in KEEP_TOOLBARS:
            # 不配圖示，直接顯示文字：少一層猜圖示的認知成本，也不必額外做一套 icon。
            bar.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            continue
        if not bar.isVisible():
            continue
        bar.hide()
        _hidden.append(bar)

    for name in HIDE_STATUS_WIDGETS:
        widget = main.statusBar().findChild(QtWidgets.QWidget, name)
        if widget is None or not widget.isVisible():
            continue
        widget.hide()
        _hidden.append(widget)

    if main.menuBar().isVisible():
        main.menuBar().hide()
        _menubar_hidden = True

    measure_panel.show()
    install_status_indicator()
    set_minimal(True)


def restore():
    """把完整的 FreeCAD 介面叫回來 —— 人類的逃生出口。"""
    global _menubar_hidden
    main = _main()
    if main is None:
        return

    for widget in _hidden:
        try:
            widget.show()
        except RuntimeError:  # Qt 那邊已經把它刪掉了
            pass
    _hidden.clear()

    if _menubar_hidden:
        main.menuBar().show()
        _menubar_hidden = False

    set_minimal(False)


def toggle():
    restore() if is_minimal() else apply()
    return is_minimal()


# --- AI 連線指示 --------------------------------------------------------

_ONLINE = "#3fb950"
_OFFLINE = "#8b949e"


class _StatusDot(QtWidgets.QLabel):
    """AI 指示燈，點一下開關通道。

    開關不放工具列：它是全場唯一按下去會讓整個產品失效的動作，
    跟「等角」「匯出」擺在一起、長得一樣大，遲早被誤按。
    放在它自己的狀態顯示上，按之前就看得到現在是開還關。
    """

    def mousePressEvent(self, _event):
        message = rpc.stop() if rpc.is_running() else rpc.start()
        App.Console.PrintMessage(f"[AgentCAD] {message}\n")
        refresh_status_indicator()


def install_status_indicator():
    """狀態列右下角一顆點：綠色代表 AI 連得進來，點一下可以開關。"""
    global _status_label
    main = _main()
    if main is None or _status_label is not None:
        return

    _status_label = _StatusDot()
    _status_label.setContentsMargins(0, 0, 12, 0)
    _status_label.setCursor(QtCore.Qt.PointingHandCursor)
    _status_label.setToolTip("AgentCAD 的 AI 控制通道。綠色代表 AI agent 連得進來；點一下可以開關。")
    main.statusBar().addPermanentWidget(_status_label)

    timer = QtCore.QTimer(_status_label)
    timer.timeout.connect(refresh_status_indicator)
    timer.start(2000)
    refresh_status_indicator()


def refresh_status_indicator():
    if _status_label is None:
        return
    try:
        running = rpc.is_running()
        port = rpc.status()["port"]
    except Exception:
        running, port = False, "?"
    color = _ONLINE if running else _OFFLINE
    text = f"AI 已就緒 · port {port}" if running else "AI 未連線"
    _status_label.setText(f'<span style="color:{color}">●</span> {text}')


# --- 首次啟動時把 AgentCAD 設為預設工作台 -------------------------------


def claim_default_workbench(name="AgentWorkbench"):
    """只做一次：把預設工作台換成 AgentCAD，之後尊重使用者的選擇。"""
    params = App.ParamGet(rpc.PARAM_PATH)
    if params.GetBool("DefaultWorkbenchClaimed", False):
        return False
    general = App.ParamGet("User parameter:BaseApp/Preferences/General")
    general.SetString("AutoloadModule", name)
    params.SetBool("DefaultWorkbenchClaimed", True)
    return True
