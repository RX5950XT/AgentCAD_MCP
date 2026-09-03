# SPDX-License-Identifier: LGPL-2.1-or-later
"""智慧測量面板 — 人類在 AgentCAD 裡唯一需要的讀數介面。

規則只有一條：**看你選了什麼，就給你最想知道的數字**。
沒選 → 整份模型的外框尺寸；選一個物件 → 長寬高／體積／重心；
選一個面或邊 → 面積／邊長／半徑；選兩個 → 距離與夾角。

量測邏輯直接呼叫 ``agentcad.tools``，跟 AI 用的是同一套大腦，
人看到的數字與 AI 讀到的數字保證一致。
"""

from collections import namedtuple

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import tools

PANEL_NAME = "AgentCAD_Measure"

# 一次點選：ref 餵給 tools（內部 Name），label／sub 給人看，doc／name 給「整體」鈕重選用。
Pick = namedtuple("Pick", "ref label sub doc name")

Q = App.Units.Quantity
LENGTH = App.Units.Length
AREA = App.Units.Area
VOLUME = App.Units.Volume

# 面板上的兩句操作說明：不寫在文件裡，寫在人正在看的地方。
HOW_TO = "沒有選取，顯示全部可見模型的外框。點面量面積、點邊量長度，按住 Ctrl 點兩個量距離。"
NEXT_PICK = " — 按住 Ctrl 再點一個就量距離"


def _describe(pick):
    return f"{pick.label}.{pick.sub}" if pick.sub else pick.label


def _fmt(value, unit=LENGTH):
    """依使用者的單位偏好格式化，避免面板寫死 mm。"""
    try:
        text = Q(float(value), unit).UserString
    except Exception:
        return f"{value}"
    # FreeCAD 給的是 cm^2／mm^3，面板上直接寫成 cm²／mm³ 比較好讀。
    text = text.replace("^2", "²").replace("^3", "³")
    # 體積 FreeCAD 標準單位制會給 ml。等值，但這裡量的是零件不是液體，cm³ 才是這行的話。
    return text.replace(" ml", " cm³") if unit == VOLUME else text


def _fmt_xyz(values):
    # `+ 0.0` 是為了把 -0.00 收成 0.00：法線常算出 -1e-17，顯示成負零很像出了錯。
    return "  ".join(f"{round(v, 2) + 0.0:.2f}" for v in values)


class MeasurePanel(QtWidgets.QWidget):
    """單欄讀數面板。顏色一律取自 QPalette，深淺色主題都自動對。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(PANEL_NAME)
        self.setMinimumWidth(270)  # XYZ 三組數字是最寬的一列，窄了會把尾數切掉

        self._headline = QtWidgets.QLabel()
        self._headline.setWordWrap(True)
        headline_font = self._headline.font()
        headline_font.setPointSizeF(headline_font.pointSizeF() * 1.05)
        headline_font.setBold(True)
        self._headline.setFont(headline_font)

        # 在 3D 視圖裡點模型只選得到面／邊／頂點，選不到整個零件（那要樹狀圖，而樹狀圖收起來了）。
        # 沒有這顆鈕，人就永遠問不出「這東西多大、多重」——3D 列印最常問的那一題。
        self._whole = self._tool_button("整體", "改量這個零件整體的大小、體積與重心", self._select_whole)
        self._copy = self._tool_button("複製", "把目前這組讀數複製成文字", self._copy_readout)
        self._clear = self._tool_button("清除", "取消選取，回到整體尺寸", Gui.Selection.clearSelection)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(4)
        header.addWidget(self._headline, 1)
        header.addWidget(self._whole)
        header.addWidget(self._copy)
        header.addWidget(self._clear)

        self._caption = QtWidgets.QLabel()
        self._caption.setWordWrap(True)
        self._caption.setForegroundRole(QtGui.QPalette.PlaceholderText)

        self._rows = QtWidgets.QGridLayout()
        self._rows.setColumnStretch(0, 0)
        self._rows.setColumnStretch(1, 1)
        self._rows.setHorizontalSpacing(12)
        self._rows.setVerticalSpacing(6)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self._caption)
        layout.addLayout(self._rows)
        layout.addStretch(1)

        self._mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self._readout = []  # (欄位, 值) —— 只為了「複製」而留
        self._whole_target = None  # (文件名, 物件名)，「整體」鈕要重選的對象
        self.refresh()

    def _tool_button(self, text, tip, slot):
        button = QtWidgets.QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        font = button.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        button.setFont(font)
        button.clicked.connect(slot)
        return button

    def _select_whole(self):
        # 先抓進區域變數：clearSelection() 會當場回呼 refresh()，把 _whole_target 清成 None。
        target = self._whole_target
        if target is None:
            return
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(*target)

    def _copy_readout(self):
        lines = [self._headline.text()] + [f"{k}\t{v}" for k, v in self._readout]
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    # --- 版面 ---

    def _clear_rows(self):
        self._readout = []
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先 setParent(None) 讓它立刻從畫面上消失；只 deleteLater 的話，
                # 舊讀數會留在原位一路畫到事件迴圈有空為止。
                widget.setParent(None)
                widget.deleteLater()

    def _add_row(self, label, value, emphasis=False):
        # 不能用 rowCount()：QGridLayout 移除項目後列數不會縮回，
        # 每刷新一次新讀數就會再往下掉一列。自己數才準。
        row = len(self._readout)
        self._readout.append((label, str(value)))

        key = QtWidgets.QLabel(label)
        key.setForegroundRole(QtGui.QPalette.PlaceholderText)

        val = QtWidgets.QLabel(str(value))
        val.setFont(self._mono)
        val.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        if emphasis:
            font = val.font()
            font.setBold(True)
            val.setFont(font)

        self._rows.addWidget(key, row, 0)
        self._rows.addWidget(val, row, 1)

    def _set_header(self, headline, caption=""):
        self._headline.setText(headline)
        self._caption.setText(caption)
        self._caption.setVisible(bool(caption))

    # --- 內容 ---

    def refresh(self):
        self._clear_rows()
        self._whole_target = None
        try:
            self._render()
        except Exception as exc:  # 面板永遠不該把主程式弄掛
            self._set_header("讀不到尺寸", str(exc))
        self._whole.setVisible(self._whole_target is not None)
        self._copy.setVisible(bool(self._readout))
        self._clear.setVisible(bool(App.GuiUp and Gui.Selection.getSelection()))

    def _render(self):
        selection = Gui.Selection.getSelectionEx() if App.GuiUp else []
        picks = []
        for item in selection:
            subs = [s for s in item.SubElementNames if s] or [None]
            for sub in subs:
                # ref 給 tools 用（吃內部 Name）；label 給人看（樹狀圖上顯示的名字）。
                ref = f"{item.Object.Name}.{sub}" if sub else item.Object.Name
                picks.append(
                    Pick(ref, item.Object.Label, sub, item.Object.Document.Name, item.Object.Name)
                )

        if not picks:
            self._render_overall()
        elif len(picks) == 1:
            self._render_single(picks[0])
        else:
            self._render_pair(picks[0], picks[1], extra=len(picks) - 2)

    def _render_overall(self):
        if App.ActiveDocument is None or not App.ActiveDocument.Objects:
            self._set_header("還沒有模型", "AI 建好模型後，尺寸會自動出現在這裡。")
            return

        box = tools.bounding_box()
        if box.get("error"):
            self._set_header("還沒有可量測的幾何", box["error"])
            return

        width, depth, height = box["size"]
        self._set_header("整體尺寸", HOW_TO)
        self._add_row("寬 X", _fmt(width), emphasis=True)
        self._add_row("深 Y", _fmt(depth), emphasis=True)
        self._add_row("高 Z", _fmt(height), emphasis=True)
        self._add_row("中心", _fmt_xyz(box["center"]))
        self._add_row("零件數", len(box["objects"]))

    def _render_single(self, pick):
        info = tools.measure(pick.ref)
        kind = info.get("kind", "")
        detail = f"{pick.sub} · " if pick.sub else ""
        if pick.sub:
            # 選在子元素上，才需要「整體」這條退路；已經在量整個零件就不用了。
            self._whole_target = (pick.doc, pick.name)

        if kind == "Face":
            self._set_header(pick.label, f"{detail}面 · {info.get('surface', '')}{NEXT_PICK}")
            self._add_row("面積", _fmt(info["area"], AREA), emphasis=True)
            if "diameter" in info:
                self._add_row("直徑", _fmt(info["diameter"]), emphasis=True)
                self._add_row("半徑", _fmt(info["radius"]))
            if "normal" in info:
                self._add_row("法線", _fmt_xyz(info["normal"]))
            return

        if kind == "Edge":
            self._set_header(pick.label, f"{detail}邊 · {info.get('curve', '')}{NEXT_PICK}")
            self._add_row("長度", _fmt(info["length"]), emphasis=True)
            if "diameter" in info:
                self._add_row("直徑", _fmt(info["diameter"]), emphasis=True)
                self._add_row("半徑", _fmt(info["radius"]))
                self._add_row("圓心", _fmt_xyz(info["center"]))
            else:
                self._add_row("起點", _fmt_xyz(info["start"]))
                self._add_row("終點", _fmt_xyz(info["end"]))
            return

        if kind == "Vertex":
            self._set_header(pick.label, f"{detail}頂點{NEXT_PICK}")
            self._add_row("座標", _fmt_xyz(info["point"]), emphasis=True)
            return

        width, depth, height = info["size"]
        self._set_header(pick.label, "單一零件")
        self._add_row("寬 X", _fmt(width), emphasis=True)
        self._add_row("深 Y", _fmt(depth), emphasis=True)
        self._add_row("高 Z", _fmt(height), emphasis=True)
        self._add_row("體積", _fmt(info["volume"], VOLUME))
        self._add_row("表面積", _fmt(info["area"], AREA))
        if info.get("center_of_mass"):
            self._add_row("重心", _fmt_xyz(info["center_of_mass"]))
        if info.get("solids", 1) > 1:
            self._add_row("獨立實體", f"{info['solids']} — 沒接合")
        if not info.get("valid", True):
            self._add_row("幾何", "無效")

    def _render_pair(self, first, second, extra=0):
        info = tools.measure(first.ref, second.ref)
        caption = f"{_describe(first)} ↔ {_describe(second)}"
        if extra:
            caption += f"（只算前兩個，另外 {extra} 個未計入）"
        self._set_header("兩者之間", caption)
        self._add_row("最短距離", _fmt(info["distance"]), emphasis=True)
        if "angle_deg" in info:
            label = "平行" if info["parallel"] else f"{info['angle_deg']}°"
            self._add_row("夾角", label, emphasis=not info["parallel"])
        # 配合間隙看的是三軸分量，不是斜線距離；從最近兩點直接算。
        gap = [abs(b - a) for a, b in zip(info["from"], info["to"])]
        if any(gap):
            self._add_row("間隙 XYZ", _fmt_xyz(gap))
        if "center_distance" in info:
            self._add_row("中心距", _fmt(info["center_distance"]))


class _SelectionWatcher:
    """選取一變動就刷新面板。FreeCAD 會在主執行緒回呼，直接更新是安全的。"""

    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, *_):
        self.panel.refresh()

    def removeSelection(self, *_):
        self.panel.refresh()

    def setSelection(self, *_):
        self.panel.refresh()

    def clearSelection(self, *_):
        self.panel.refresh()


class _DocumentWatcher:
    """模型被 AI 改動後刷新面板。用事件而不是輪詢，數字才不會在你選字時被洗掉。"""

    def __init__(self, panel):
        self.panel = panel

    def slotRecomputedDocument(self, _doc):
        self.panel.refresh()

    def slotDeletedObject(self, _obj):
        self.panel.refresh()

    def slotActivateDocument(self, _doc):
        self.panel.refresh()


_panel = None
_watcher = None
_doc_watcher = None


def show():
    """建立（或叫回）測量面板。"""
    global _panel, _watcher, _doc_watcher
    main = Gui.getMainWindow()

    existing = main.findChild(QtWidgets.QDockWidget, PANEL_NAME + "_Dock")
    if existing is not None:
        existing.setVisible(True)
        existing.raise_()
        if _panel is not None:
            _panel.refresh()
        return _panel

    _panel = MeasurePanel()
    dock = QtWidgets.QDockWidget("尺寸", main)
    dock.setObjectName(PANEL_NAME + "_Dock")
    dock.setWidget(_panel)
    dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetClosable)
    main.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    _watcher = _SelectionWatcher(_panel)
    Gui.Selection.addObserver(_watcher)

    _doc_watcher = _DocumentWatcher(_panel)
    App.addDocumentObserver(_doc_watcher)
    return _panel


def toggle():
    main = Gui.getMainWindow()
    dock = main.findChild(QtWidgets.QDockWidget, PANEL_NAME + "_Dock")
    if dock is None:
        show()
        return True
    dock.setVisible(not dock.isVisible())
    return dock.isVisible()
