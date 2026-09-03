# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 自我檢查：對著執行中的 AgentCAD 跑一遍，確認 AI 通道還活著。

用法（AgentCAD 視窗要開著）：

    python smoke.py

檢查兩件事：舊 freecad-mcp 用戶端還能用（相容層沒壞），以及新工具算得對。
"""

import base64
import os
import sys
import tempfile
import xmlrpc.client

URL = os.environ.get("AGENTCAD_URL", "http://127.0.0.1:9875")
DOC = "AgentCAD_SelfTest"


def unwrap(payload):
    assert payload["success"], payload.get("error")
    return payload["result"]


def main():
    rpc = xmlrpc.client.ServerProxy(URL, allow_none=True)
    assert rpc.ping() is True

    rpc.create_document(DOC)
    try:
        # 60x40x10 的板子，中間挖一個 R6 貫穿孔。
        assert rpc.execute_code(
            f"""
import FreeCAD as App
doc = App.getDocument({DOC!r})
box = doc.addObject("Part::Box", "Plate")
box.Length, box.Width, box.Height = 60, 40, 10
hole = doc.addObject("Part::Cylinder", "Hole")
hole.Radius, hole.Height = 6, 30
hole.Placement.Base = App.Vector(30, 20, -5)
cut = doc.addObject("Part::Cut", "Bracket")
cut.Base, cut.Tool = box, hole
doc.addObject("Part::Box", "Scratch")  # 只為了測 delete_object，沒有人依賴它
doc.recompute()
"""
        )["success"]

        # 相容層：舊用戶端讀得到屬性（Quantity 要是數值，不是 <error: ...>）。
        legacy = rpc.get_object(DOC, "Plate")
        assert legacy["Properties"]["Length"] == 60.0, legacy["Properties"]["Length"]
        assert len(rpc.get_objects(DOC)) == 4

        # 非同步任務不可以污染下一個同步呼叫的回應。
        rpc.execute_code_async("pass")
        assert rpc.delete_object(DOC, "Scratch")["object_name"] == "Scratch"

        # 量測：板子外框，以及孔的直徑。
        box = unwrap(rpc.bounding_box(["Bracket"], DOC))
        assert box["size"] == [60.0, 40.0, 10.0], box["size"]

        hole_face = unwrap(rpc.measure("Bracket.Face7", None, DOC))
        assert abs(hole_face["diameter"] - 12.0) < 1e-6, hole_face

        # 幾何健檢：挖完孔應該還是單一實體。
        health = unwrap(rpc.check_geometry("Bracket", DOC))
        assert health["ok"], health["problems"]
        assert health["solids"] == 1

        # 體積 = 板 24000 減掉孔 π*6²*10。
        mass = unwrap(rpc.mass_properties("Bracket", None, DOC))
        assert abs(mass["volume_mm3"] - (24000 - 3.14159265 * 36 * 10)) < 1.0, mass

        # 截圖與匯出。
        shots = unwrap(rpc.capture(["isometric", "top"], 320, 240, None, DOC))
        assert len(shots) == 2 and all(base64.b64decode(s["png_base64"]) for s in shots)

        target = os.path.join(tempfile.mkdtemp(), "bracket.stl")
        assert unwrap(rpc.export_model(target, ["Bracket"], DOC))["bytes"] > 0
        os.remove(target)
    finally:
        rpc.execute_code(f"import FreeCAD as App; App.closeDocument({DOC!r})")

    print("AgentCAD 自我檢查全部通過")


if __name__ == "__main__":
    try:
        main()
    except ConnectionRefusedError:
        sys.exit(f"連不上 AgentCAD（{URL}）；請先開啟 AgentCAD 視窗。")
