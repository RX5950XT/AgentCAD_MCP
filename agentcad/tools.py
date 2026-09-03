# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 給 AI 用的工具集。

全部函式都在 GUI 主執行緒上被呼叫（由 rpc.on_gui 排程），因此可以直接碰文件與 3D 視圖。
回傳一律是可 JSON 化的 dict／list。
"""

import base64
import math
import os
import tempfile

import FreeCAD as App

from . import serialize

VIEW_METHODS = {
    "isometric": "viewIsometric",
    "front": "viewFront",
    "back": "viewBack",
    "left": "viewLeft",
    "right": "viewRight",
    "top": "viewTop",
    "bottom": "viewBottom",
    "dimetric": "viewDimetric",
    "trimetric": "viewTrimetric",
}

MESH_FORMATS = frozenset([".stl", ".obj", ".3mf", ".ply", ".amf", ".off"])
SHAPE_FORMATS = frozenset([".step", ".stp", ".iges", ".igs", ".brep", ".brp"])


def _gui():
    import FreeCADGui

    return FreeCADGui


def get_doc(doc_name=None):
    """取得文件；doc_name 為 None 時用作用中文件。

    關掉一份文件之後 FreeCAD 會把 ActiveDocument 設成 None，即使還有別的文件開著。
    只剩一份時直接拿它用，省得 AI 為了這個多繞一趟。
    """
    if doc_name:
        doc = App.getDocument(doc_name)
        if doc is None:
            raise ValueError(f"找不到文件 '{doc_name}'")
        return doc

    doc = App.ActiveDocument
    if doc is not None:
        return doc

    names = list(App.listDocuments())
    if len(names) == 1:
        return App.getDocument(names[0])
    if not names:
        raise ValueError("目前沒有開啟任何文件")
    raise ValueError(f"沒有作用中的文件，請指定 doc_name，開啟中的有：{names}")


def _active_view(doc_name=None):
    """取得可截圖的 3D 視圖，必要時先把文件設為作用中。"""
    gui = _gui()
    if gui.ActiveDocument is None:
        gui.ActiveDocument = gui.getDocument(get_doc(doc_name).Name)
    view = gui.ActiveDocument.ActiveView
    if not hasattr(view, "saveImage"):
        raise RuntimeError("目前的分頁不是 3D 視圖（可能停在開始頁／TechDraw／試算表）")
    return view


def resolve(doc, ref):
    """把 'Box' 或 'Box.Face3' 解析成 (物件, 形狀, 子元素名)。"""
    sub = None
    name = ref
    if "." in ref:
        name, sub = ref.split(".", 1)
    obj = doc.getObject(name)
    if obj is None:
        for candidate in doc.Objects:
            if candidate.Label == name:
                obj = candidate
                break
    if obj is None:
        raise ValueError(f"找不到物件 '{name}'")
    shape = getattr(obj, "Shape", None)
    if shape is None:
        raise ValueError(f"'{name}' 沒有幾何形狀")
    if sub:
        shape = shape.getElement(sub)
    return obj, shape, sub


# --- 場景 ---------------------------------------------------------------


def scene_digest(doc_name=None):
    return serialize.digest(get_doc(doc_name))


def list_errors(doc_name=None):
    doc = get_doc(doc_name)
    return {
        "document": doc.Name,
        "errors": serialize.digest(doc)["errors"],
        "touched": [o.Name for o in doc.Objects if o.mustExecute()],
    }


def recompute(doc_name=None, force=True):
    doc = get_doc(doc_name)
    doc.recompute(None, force)
    return list_errors(doc.Name)


def set_visibility(names, visible=True, doc_name=None):
    doc = get_doc(doc_name)
    changed = []
    for name in names:
        obj = doc.getObject(name)
        if obj is not None and getattr(obj, "ViewObject", None) is not None:
            obj.ViewObject.Visibility = bool(visible)
            changed.append(name)
    return {"changed": changed, "visible": bool(visible)}


def undo(steps=1, doc_name=None):
    doc = get_doc(doc_name)
    for _ in range(max(1, int(steps))):
        doc.undo()
    doc.recompute()
    return {"undone": steps, "document": doc.Name}


def redo(steps=1, doc_name=None):
    doc = get_doc(doc_name)
    for _ in range(max(1, int(steps))):
        doc.redo()
    doc.recompute()
    return {"redone": steps, "document": doc.Name}


# --- 量測 ---------------------------------------------------------------


def _element_info(shape, sub):
    """單一元素的量測結果，依型別給最有用的數字。"""
    kind = shape.ShapeType
    if kind == "Vertex":
        return {"element": sub, "kind": "Vertex", "point": serialize._xyz(shape.Point)}

    if kind == "Edge":
        info = {
            "element": sub,
            "kind": "Edge",
            "length": serialize._r(shape.Length),
            "curve": type(shape.Curve).__name__,
            "start": serialize._xyz(shape.Vertexes[0].Point),
            "end": serialize._xyz(shape.Vertexes[-1].Point),
        }
        radius = getattr(shape.Curve, "Radius", None)
        if radius is not None:
            info["radius"] = serialize._r(radius)
            info["diameter"] = serialize._r(radius * 2)
            info["center"] = serialize._xyz(shape.Curve.Center)
        return info

    if kind == "Face":
        info = {
            "element": sub,
            "kind": "Face",
            "area": serialize._r(shape.Area),
            "surface": type(shape.Surface).__name__,
        }
        try:
            umid = sum(shape.ParameterRange[0:2]) / 2
            vmid = sum(shape.ParameterRange[2:4]) / 2
            info["normal"] = serialize._xyz(shape.normalAt(umid, vmid))
        except Exception:
            pass
        radius = getattr(shape.Surface, "Radius", None)
        if radius is not None:
            info["radius"] = serialize._r(radius)
            info["diameter"] = serialize._r(radius * 2)
        return info

    return serialize.shape_summary(shape)


def _angle_between(a, b):
    dot = max(-1.0, min(1.0, a.dot(b) / (a.Length * b.Length)))
    deg = math.degrees(math.acos(dot))
    return serialize._r(180.0 - deg if deg > 90 else deg, 3)


def _direction(shape):
    """取形狀的代表方向：平面用法線、直線用切線，其餘 None。"""
    if shape.ShapeType == "Face":
        try:
            umid = sum(shape.ParameterRange[0:2]) / 2
            vmid = sum(shape.ParameterRange[2:4]) / 2
            return shape.normalAt(umid, vmid)
        except Exception:
            return None
    if shape.ShapeType == "Edge" and type(shape.Curve).__name__ == "Line":
        return shape.tangentAt(shape.FirstParameter)
    return None


def measure(a, b=None, doc_name=None):
    """智慧量測。

    一個目標 → 該元素最有意義的尺寸（邊長／面積／半徑／整體外框）。
    兩個目標 → 最短距離，能判斷時再補上角度與中心距。
    目標寫法：``"Box"``、``"Box.Face3"``、``"Cylinder.Edge1"``。
    """
    doc = get_doc(doc_name)
    _, shape_a, sub_a = resolve(doc, a)

    if b is None:
        if sub_a:
            return {"target": a, **_element_info(shape_a, sub_a)}
        return {"target": a, "kind": "Object", **serialize.shape_summary(shape_a)}

    _, shape_b, _ = resolve(doc, b)
    dist, points, _ = shape_a.distToShape(shape_b)
    result = {
        "targets": [a, b],
        "distance": serialize._r(dist),
        "from": serialize._xyz(points[0][0]),
        "to": serialize._xyz(points[0][1]),
    }

    dir_a, dir_b = _direction(shape_a), _direction(shape_b)
    if dir_a is not None and dir_b is not None:
        angle = _angle_between(dir_a, dir_b)
        result["angle_deg"] = angle
        result["parallel"] = angle < 0.001

    try:
        centre_gap = shape_a.CenterOfMass.sub(shape_b.CenterOfMass)
        result["center_distance"] = serialize._r(centre_gap.Length)
        result["center_delta"] = serialize._xyz(centre_gap)
    except Exception:
        pass
    return result


def bounding_box(names=None, doc_name=None):
    """整體或指定物件的外框尺寸。

    不給 names 時只算「看得見的」物件 —— 布林運算後被藏起來的原料件不該灌水成品尺寸。
    """
    doc = get_doc(doc_name)
    if names:
        objects = [doc.getObject(n) for n in names]
    else:
        objects = [o for o in doc.Objects if getattr(getattr(o, "ViewObject", None), "Visibility", True)]
        if not objects:
            objects = list(doc.Objects)
    box = None
    used = []
    for obj in objects:
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        box = shape.BoundBox if box is None else box.united(shape.BoundBox)
        used.append(obj.Name)
    if box is None:
        return {"objects": [], "error": "沒有可量測的幾何"}
    return {
        "objects": used,
        "size": [serialize._r(box.XLength), serialize._r(box.YLength), serialize._r(box.ZLength)],
        "min": [serialize._r(box.XMin), serialize._r(box.YMin), serialize._r(box.ZMin)],
        "max": [serialize._r(box.XMax), serialize._r(box.YMax), serialize._r(box.ZMax)],
        "center": [
            serialize._r(box.Center.x),
            serialize._r(box.Center.y),
            serialize._r(box.Center.z),
        ],
    }


def check_geometry(obj_name, doc_name=None):
    """幾何健檢：是否有效、是否單一實體、是否封閉、體積是否合理。"""
    doc = get_doc(doc_name)
    obj, shape, _ = resolve(doc, obj_name)
    problems = []
    if not shape.isValid():
        problems.append("形狀無效（isValid=False）")
    if len(shape.Solids) > 1:
        problems.append(f"含 {len(shape.Solids)} 個獨立實體，布林運算可能沒接上")
    if shape.ShapeType == "Solid" and not shape.isClosed():
        problems.append("實體未封閉")
    if shape.Volume <= 1e-9:
        problems.append("體積為零，可能是空形狀或全被切掉")
    if "Invalid" in obj.State or "Error" in obj.State:
        problems.append(f"物件狀態異常：{obj.State}")
    return {
        "object": obj.Name,
        "ok": not problems,
        "problems": problems,
        **serialize.shape_summary(shape),
    }


def check_interference(a, b, doc_name=None):
    """兩物件是否干涉，以及干涉體積 — 組裝與壓配設計必查。"""
    doc = get_doc(doc_name)
    _, shape_a, _ = resolve(doc, a)
    _, shape_b, _ = resolve(doc, b)
    common = shape_a.common(shape_b)
    volume = common.Volume if not common.isNull() else 0.0
    gap = None
    if volume <= 1e-9:
        gap = serialize._r(shape_a.distToShape(shape_b)[0])
    return {
        "targets": [a, b],
        "interferes": volume > 1e-9,
        "overlap_volume": serialize._r(volume, 3),
        "gap": gap,
    }


def mass_properties(obj_name, density=None, doc_name=None):
    """體積、表面積、重心；給 density（g/cm³）就一併算重量。"""
    doc = get_doc(doc_name)
    obj, shape, _ = resolve(doc, obj_name)
    out = {
        "object": obj.Name,
        "volume_mm3": serialize._r(shape.Volume, 3),
        "area_mm2": serialize._r(shape.Area, 3),
    }
    centre = serialize.center_of_mass(shape)
    if centre is not None:
        out["center_of_mass"] = centre
    if density:
        out["density_g_cm3"] = density
        out["mass_g"] = serialize._r(shape.Volume / 1000.0 * float(density), 3)
    return out


# --- 視圖 ---------------------------------------------------------------


def set_view(view=None, fit=True, zoom=None, doc_name=None):
    """切換標準視角／縮放至適合。"""
    active = _active_view(doc_name)
    if view:
        method = VIEW_METHODS.get(str(view).lower())
        if method is None:
            raise ValueError(f"未知視角 '{view}'，可用：{sorted(VIEW_METHODS)}")
        getattr(active, method)()
    if zoom:
        active.zoomIn() if float(zoom) > 1 else active.zoomOut()
    if fit:
        active.fitAll()
    return {"view": view, "fit": bool(fit)}


def _save_png(active, path, width, height):
    if width and height:
        active.saveImage(path, int(width), int(height))
    else:
        active.saveImage(path)
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("utf-8")


def capture(views=("isometric",), width=800, height=600, focus=None, doc_name=None):
    """一次抓多個視角的截圖，回傳 base64 PNG 清單。

    AI 一次呼叫就能同時看到前視／上視／等角，判斷比例遠比單張準。
    """
    gui = _gui()
    active = _active_view(doc_name)

    if focus:
        doc = get_doc(doc_name)
        obj = doc.getObject(focus)
        if obj is not None:
            gui.Selection.clearSelection()
            gui.Selection.addSelection(obj)

    images = []
    handle, tmp = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        for view in views:
            method = VIEW_METHODS.get(str(view).lower())
            if method is None:
                continue
            getattr(active, method)()
            if focus:
                gui.SendMsgToActiveView("ViewSelection")
            else:
                active.fitAll()
            images.append({"view": view, "png_base64": _save_png(active, tmp, width, height)})
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return images


# --- 匯出 ---------------------------------------------------------------


def export_model(path, names=None, doc_name=None):
    """依副檔名匯出 STEP／STL／3MF／OBJ／IGES／BREP。"""
    doc = get_doc(doc_name)
    objects = [doc.getObject(n) for n in names] if names else list(doc.Objects)
    objects = [o for o in objects if o is not None and getattr(o, "Shape", None) is not None]
    if not objects:
        raise ValueError("沒有可匯出的物件")

    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    if ext in SHAPE_FORMATS:
        import Part

        Part.export(objects, path)
    elif ext in MESH_FORMATS:
        import Mesh

        Mesh.export(objects, path)
    else:
        allowed = sorted(SHAPE_FORMATS | MESH_FORMATS)
        raise ValueError(f"不支援的格式 '{ext}'，可用：{allowed}")
    return {"path": path, "objects": [o.Name for o in objects], "bytes": os.path.getsize(path)}


def save_document(path=None, doc_name=None):
    doc = get_doc(doc_name)
    if path:
        doc.saveAs(os.path.abspath(path))
    else:
        doc.save()
    return {"document": doc.Name, "path": doc.FileName}
