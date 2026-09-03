# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2"]
# ///
# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD MCP server — 讓 Claude Code / Codex 直接操控 AgentCAD。

啟動方式（不需安裝，uv 會自己處理相依）：

    claude mcp add agentcad -s user -- uv run --script <本檔絕對路徑>

AgentCAD 視窗要開著，且狀態列的 AI 指示燈是綠的。
連線位址可用環境變數 AGENTCAD_URL 覆寫，預設 http://127.0.0.1:9875。
"""

import base64
import json
import os
import xmlrpc.client
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

URL = os.environ.get("AGENTCAD_URL", "http://127.0.0.1:9875")
server = MCPServer("agentcad")


def call(method: str, *args: Any) -> Any:
    """呼叫 AgentCAD 的 RPC 方法，把連線問題翻成人看得懂的訊息。"""
    try:
        proxy = xmlrpc.client.ServerProxy(URL, allow_none=True)
        return getattr(proxy, method)(*args)
    except ConnectionRefusedError:
        raise RuntimeError(
            f"連不上 AgentCAD（{URL}）。請確認 AgentCAD 視窗已開啟，"
            "且狀態列的 AI 指示燈是綠色的。"
        )
    except xmlrpc.client.Fault as fault:
        raise RuntimeError(f"AgentCAD 回報錯誤：{fault.faultString}")


def unwrap(payload: Any) -> Any:
    """擴充工具統一包成 {success, result}；失敗就直接丟例外讓 AI 看到原因。"""
    if isinstance(payload, dict) and "success" in payload:
        if not payload["success"]:
            raise RuntimeError(payload.get("error", "未知錯誤"))
        return payload.get("result", payload)
    return payload


def as_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --- 看場景 -------------------------------------------------------------


@server.tool()
def scene(document: str | None = None) -> str:
    """看目前模型的全貌：每個物件的長寬高、體積、位置、可調參數與錯誤狀態。

    這是建模前後最該先呼叫的工具，比 get_objects 精簡很多，適合反覆確認進度。
    """
    return as_json(unwrap(call("scene_digest", document)))


@server.tool()
def documents() -> str:
    """列出所有開啟中的文件名稱。"""
    return as_json(call("list_documents"))


@server.tool()
def problems(document: str | None = None) -> str:
    """列出有錯誤或還沒重算的物件。建模卡住時先看這個。"""
    return as_json(unwrap(call("list_errors", document)))


@server.tool()
def capabilities() -> str:
    """列出 AgentCAD 提供的全部工具與說明。"""
    return as_json(call("list_tools"))


# --- 動手建模 -----------------------------------------------------------


@server.tool()
def run_code(code: str) -> str:
    """在 AgentCAD 裡執行 Python，擁有完整的 FreeCAD API 權限。

    這是最強也最常用的建模手段：Part / PartDesign / Draft / Sketcher / Mesh 全部可用。
    變數會跨次呼叫保留，可以分段建構。範例：

        import Part, FreeCAD as App
        doc = App.ActiveDocument
        box = doc.addObject("Part::Box", "Base")
        box.Length, box.Width, box.Height = 40, 30, 10
        doc.recompute()
    """
    result = call("execute_code", code)
    if not result.get("success"):
        raise RuntimeError(result.get("error", "執行失敗"))
    return result.get("message", "OK")


@server.tool()
def new_document(name: str = "Model") -> str:
    """新建文件。"""
    return as_json(call("create_document", name))


@server.tool()
def create_object(document: str, type_id: str, name: str, properties: dict | None = None) -> str:
    """建立物件，例如 type_id="Part::Box"、properties={"Length": 40, "Height": 10}。"""
    payload = {"Name": name, "Type": type_id, "Properties": properties or {}}
    return as_json(call("create_object", document, payload))


@server.tool()
def edit_object(document: str, name: str, properties: dict) -> str:
    """修改既有物件的屬性。"""
    return as_json(call("edit_object", document, name, {"Properties": properties}))


@server.tool()
def delete_object(document: str, name: str) -> str:
    """刪除物件。"""
    return as_json(call("delete_object", document, name))


@server.tool()
def recompute(document: str | None = None) -> str:
    """強制重算整份文件，並回報還有哪些錯誤。"""
    return as_json(unwrap(call("recompute", document, True)))


@server.tool()
def undo(steps: int = 1, document: str | None = None) -> str:
    """回上一步。建模走錯路時比重建整個模型快。"""
    return as_json(unwrap(call("undo", steps, document)))


@server.tool()
def redo(steps: int = 1, document: str | None = None) -> str:
    """把剛剛復原的動作再做回來。"""
    return as_json(unwrap(call("redo", steps, document)))


# --- 量測與檢查 ---------------------------------------------------------


@server.tool()
def measure(target: str, other: str | None = None, document: str | None = None) -> str:
    """智慧量測。

    一個目標 → 給該元素最有意義的尺寸；兩個目標 → 給最短距離、夾角與中心距。
    目標寫法：``"Box"``（整個物件）、``"Box.Face3"``（面）、``"Cyl.Edge1"``（邊）。
    """
    return as_json(unwrap(call("measure", target, other, document)))


@server.tool()
def bounding_box(names: list[str] | None = None, document: str | None = None) -> str:
    """外框尺寸。不給 names 就量整份文件 —— 確認成品尺寸是否符合需求時用這個。"""
    return as_json(unwrap(call("bounding_box", names, document)))


@server.tool()
def check_geometry(name: str, document: str | None = None) -> str:
    """幾何健檢：形狀是否有效、是否變成多個沒接合的實體、是否封閉、體積是否為零。

    布林運算之後一定要跑一次；「看起來對但其實是兩塊」是最常見的隱形失敗。
    """
    return as_json(unwrap(call("check_geometry", name, document)))


@server.tool()
def check_interference(first: str, second: str, document: str | None = None) -> str:
    """兩個零件是否干涉、重疊多少體積；沒干涉時回報間隙。組裝與壓配設計必查。"""
    return as_json(unwrap(call("check_interference", first, second, document)))


@server.tool()
def mass_properties(name: str, density: float | None = None) -> str:
    """體積、表面積、重心；給 density（g/cm³，PLA 約 1.24）就一併估重量。"""
    return as_json(unwrap(call("mass_properties", name, density)))


# --- 看畫面 -------------------------------------------------------------


@server.tool()
def screenshot(
    views: list[str] | None = None,
    width: int = 800,
    height: int = 600,
    focus: str | None = None,
) -> list[Image]:
    """截圖看建模成果。可一次要多個視角，判斷比例遠比單張準。

    views 可用：isometric, front, back, left, right, top, bottom, dimetric, trimetric。
    預設 ["isometric"]。focus 給物件名稱就只對焦那個零件。
    """
    shots = unwrap(call("capture", views or ["isometric"], width, height, focus))
    return [Image(data=base64.b64decode(shot["png_base64"]), format="png") for shot in shots]


@server.tool()
def set_view(view: str = "isometric", fit: bool = True) -> str:
    """轉動視角。之後再截圖就會是這個角度。"""
    return as_json(unwrap(call("set_view", view, fit, None, None)))


@server.tool()
def set_visibility(names: list[str], visible: bool = True, document: str | None = None) -> str:
    """顯示或隱藏物件。截圖前把擋住的零件藏起來，看內部結構很好用。"""
    return as_json(unwrap(call("set_visibility", names, visible, document)))


# --- 交件 ---------------------------------------------------------------


@server.tool()
def export_model(path: str, names: list[str] | None = None, document: str | None = None) -> str:
    """匯出成品。依副檔名決定格式：

    STEP/IGES/BREP 走實體，STL/3MF/OBJ/PLY 走網格（3D 列印用 STL 或 3MF）。
    """
    return as_json(unwrap(call("export_model", path, names, document)))


@server.tool()
def save_document(path: str | None = None, document: str | None = None) -> str:
    """存檔。第一次存要給 .FCStd 的完整路徑。"""
    return as_json(unwrap(call("save_document", path, document)))


def main():
    server.run()


if __name__ == "__main__":
    main()
