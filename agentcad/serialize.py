# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 序列化層。

兩種格式：
  * ``serialize_object`` — 與既有 freecad-mcp 用戶端相容的完整格式（不可任意更動）。
  * ``brief`` / ``digest`` — 給 AI 用的緊湊格式，只留決策需要的欄位，省 token。
"""

import FreeCAD as App


def _r(x, nd=4):
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return x


def _xyz(v):
    return [_r(v.x), _r(v.y), _r(v.z)]


def center_of_mass(shape):
    """重心；取不到就回 None。

    布林運算的結果是 Compound，Compound 沒有 ``CenterOfMass``（只有 Solid 有），
    問錯屬性就會安靜地少一列重心 —— 而那正是最常被布林運算切出來的零件。
    """
    for attr in ("CenterOfMass", "CenterOfGravity"):
        vector = getattr(shape, attr, None)
        if vector is not None:
            return _xyz(vector)
    return None


# --- 相容格式（沿用舊 freecad-mcp addon 的輸出，勿改欄位） ----------------


# FreeCAD 1.2 把 Color 從 FreeCAD 搬走了，直接寫 App.Color 會 AttributeError，
# 而且那個例外會讓每個 Quantity 屬性都變成 <error: ...>。
COLOR_TYPE = getattr(App, "Color", None) or getattr(getattr(App, "Base", None), "Color", None)


def serialize_value(value):
    if isinstance(value, (int, float, str, bool)):
        return value
    elif isinstance(value, App.Vector):
        return {"x": value.x, "y": value.y, "z": value.z}
    elif isinstance(value, App.Rotation):
        return {
            "Axis": {"x": value.Axis.x, "y": value.Axis.y, "z": value.Axis.z},
            "Angle": value.Angle,
        }
    elif isinstance(value, App.Placement):
        return {
            "Base": serialize_value(value.Base),
            "Rotation": serialize_value(value.Rotation),
        }
    elif isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    elif COLOR_TYPE is not None and isinstance(value, COLOR_TYPE):
        return tuple(value)
    try:
        # Quantity（10 mm、360 deg…）給數值比給字串好用。
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def serialize_shape(shape):
    if shape is None:
        return None
    return {
        "Volume": shape.Volume,
        "Area": shape.Area,
        "VertexCount": len(shape.Vertexes),
        "EdgeCount": len(shape.Edges),
        "FaceCount": len(shape.Faces),
    }


def serialize_view_object(view):
    if view is None:
        return None
    return {
        "ShapeColor": serialize_value(view.ShapeColor),
        "Transparency": view.Transparency,
        "Visibility": view.Visibility,
    }


def serialize_object(obj):
    if isinstance(obj, list):
        return [serialize_object(item) for item in obj]
    if isinstance(obj, App.Document):
        return {
            "Name": obj.Name,
            "Label": obj.Label,
            "FileName": obj.FileName,
            "Objects": [serialize_object(child) for child in obj.Objects],
        }
    if obj is None:
        return None

    result = {
        "Name": obj.Name,
        "Label": obj.Label,
        "TypeId": obj.TypeId,
        "Properties": {},
        "Placement": serialize_value(getattr(obj, "Placement", None)),
        "Shape": serialize_shape(getattr(obj, "Shape", None)),
        "ViewObject": {},
    }
    for prop in obj.PropertiesList:
        try:
            result["Properties"][prop] = serialize_value(getattr(obj, prop))
        except Exception as exc:
            result["Properties"][prop] = f"<error: {exc}>"

    view = getattr(obj, "ViewObject", None)
    if view is not None:
        result["ViewObject"] = serialize_view_object(view)
    return result


# --- 緊湊格式（AI 專用） ------------------------------------------------

# 只把「AI 改得動、看得懂」的參數型別放進 params，其餘略過以省 token。
PARAM_TYPES = frozenset(
    [
        "App::PropertyLength",
        "App::PropertyDistance",
        "App::PropertyFloat",
        "App::PropertyFloatConstraint",
        "App::PropertyInteger",
        "App::PropertyIntegerConstraint",
        "App::PropertyBool",
        "App::PropertyAngle",
        "App::PropertyString",
        "App::PropertyEnumeration",
        "App::PropertyArea",
        "App::PropertyPercent",
    ]
)

# Attacher 相關屬性是 FreeCAD 的內部接合機制，對 AI 判讀尺寸只是雜訊。
PARAM_SKIP = frozenset(
    [
        "Label",
        "Label2",
        "Visibility",
        "ExpressionEngine",
        "MapMode",
        "MapReversed",
        "MapPathParameter",
    ]
)


def params(obj):
    """物件可調參數（Length/Radius/Angle...），已過濾雜訊。"""
    out = {}
    for prop in obj.PropertiesList:
        if prop in PARAM_SKIP or prop.startswith(("Attach", "_")):
            continue
        try:
            if obj.getTypeIdOfProperty(prop) not in PARAM_TYPES:
                continue
            status = obj.getPropertyStatus(prop)
            if "Hidden" in status or "ReadOnly" in status:
                continue
            value = getattr(obj, prop)
            # bool/int/str 原樣保留（True 不該變成 1.0）；其餘（含 Quantity）轉成短浮點數，
            # 因為 Quantity 沒辦法經由 XML-RPC 傳出去。
            out[prop] = value if isinstance(value, (bool, int, str)) else _r(value)
        except Exception:
            continue
    return out


def shape_summary(shape):
    """形狀摘要：尺寸、體積、拓樸數量、有效性。"""
    if shape is None or shape.isNull():
        return None
    bb = shape.BoundBox
    info = {
        "size": [_r(bb.XLength), _r(bb.YLength), _r(bb.ZLength)],
        "bbox_min": [_r(bb.XMin), _r(bb.YMin), _r(bb.ZMin)],
        "bbox_max": [_r(bb.XMax), _r(bb.YMax), _r(bb.ZMax)],
        "volume": _r(shape.Volume, 3),
        "area": _r(shape.Area, 3),
        "solids": len(shape.Solids),
        "faces": len(shape.Faces),
        "shape_type": shape.ShapeType,
        "valid": bool(shape.isValid()),
    }
    centre = center_of_mass(shape)
    if centre is not None:
        info["center_of_mass"] = centre
    return info


def brief(obj):
    """單一物件的緊湊描述。"""
    out = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "pos": _xyz(obj.Placement.Base) if hasattr(obj, "Placement") else None,
    }
    view = getattr(obj, "ViewObject", None)
    if view is not None:
        out["visible"] = bool(view.Visibility)

    rot = getattr(obj, "Placement", None)
    if rot is not None and abs(rot.Rotation.Angle) > 1e-9:
        out["rot"] = {
            "axis": _xyz(rot.Rotation.Axis),
            "angle_deg": _r(rot.Rotation.Angle * 180.0 / 3.141592653589793, 3),
        }

    shape = shape_summary(getattr(obj, "Shape", None))
    if shape:
        out.update(shape)

    prm = params(obj)
    if prm:
        out["params"] = prm

    if obj.State and "Invalid" in obj.State:
        out["state"] = obj.State
    return out


def digest(doc):
    """整份文件的緊湊摘要 — 取代肥大的 get_objects。"""
    objects = [brief(o) for o in doc.Objects]
    errors = []
    for obj in doc.Objects:
        if "Invalid" in obj.State or "Error" in obj.State:
            errors.append({"name": obj.Name, "state": obj.State})
        shape = getattr(obj, "Shape", None)
        if shape is not None and not shape.isNull() and not shape.isValid():
            errors.append({"name": obj.Name, "state": "InvalidShape"})

    visible = [o for o in doc.Objects if getattr(getattr(o, "ViewObject", None), "Visibility", False)]
    overall = None
    for obj in visible:
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        bb = shape.BoundBox
        overall = bb if overall is None else overall.united(bb)

    out = {
        "document": doc.Name,
        "label": doc.Label,
        "file": doc.FileName,
        "object_count": len(doc.Objects),
        "objects": objects,
        "errors": errors,
    }
    if overall is not None:
        out["overall_size"] = [_r(overall.XLength), _r(overall.YLength), _r(overall.ZLength)]
    return out
