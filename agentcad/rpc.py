# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD 內建 RPC 伺服器。

AI agent 的唯一控制入口。設計重點：

* **相容**：方法名與回傳格式跟既有 ``freecad-mcp`` 用戶端完全一致，舊有 AI 操作不受影響。
* **擴充**：``agentcad.tools`` 裡的工具全部自動註冊，AI 拿到的能力遠多於原本。
* **執行緒安全**：RPC 在背景執行緒收請求，實際動作一律排到 GUI 主執行緒執行。
"""

import contextlib
import io
import ipaddress
import queue
import threading
from xmlrpc.server import SimpleXMLRPCServer

import FreeCAD as App

from . import serialize, tools

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/Agent"
DEFAULT_PORT = 9875
GUI_TIMEOUT = 60.0  # 秒；單次 GUI 動作的上限，避免 RPC 永久卡住
PUMP_INTERVAL = 50  # 毫秒

_requests = queue.Queue()
_results = queue.Queue()
_server = None
_thread = None
_pumping = False

# execute_code 的持久命名空間：AI 分多次送的程式碼可以共用變數。
_exec_globals = {"__name__": "__agentcad__"}


def settings():
    return App.ParamGet(PARAM_PATH)


def _pump():
    """在 GUI 主執行緒上消化排隊的動作。

    佇列裡放的是 (動作, 要不要回結果)。非同步的動作不回結果 —— 否則它的回傳值
    會留在 _results 裡，被下一個同步呼叫誤讀成自己的答案。
    """
    while not _requests.empty():
        task, wants_result = _requests.get()
        try:
            value = task()
        except Exception as exc:
            if wants_result:
                _results.put(("err", f"{type(exc).__name__}: {exc}"))
            else:
                App.Console.PrintError(f"[AgentCAD] 背景動作失敗：{exc}\n")
            continue
        if wants_result:
            _results.put(("ok", value))
    from PySide import QtCore

    QtCore.QTimer.singleShot(PUMP_INTERVAL, _pump)


def start_pump():
    global _pumping
    if _pumping:
        return
    _pumping = True
    _pump()


def on_gui(func, *args, **kwargs):
    """把 func 排到 GUI 主執行緒執行並等結果；失敗時丟出例外。"""
    _requests.put((lambda: func(*args, **kwargs), True))
    try:
        status, payload = _results.get(timeout=GUI_TIMEOUT)
    except queue.Empty:
        raise TimeoutError(f"GUI 逾時（>{GUI_TIMEOUT}s），動作可能被對話框卡住")
    if status == "err":
        raise RuntimeError(payload)
    return payload


def _envelope(func, *args, **kwargs):
    """統一的 success/error 回傳格式。"""
    try:
        return {"success": True, "result": on_gui(func, *args, **kwargs)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# --- 相容層：沿用舊 addon 的物件建立語意 --------------------------------


def _set_properties(doc, obj, properties):
    for prop, val in properties.items():
        try:
            if prop in obj.PropertiesList:
                if prop == "Placement" and isinstance(val, dict):
                    pos = val.get("Base") or val.get("Position") or {}
                    rot = val.get("Rotation", {})
                    axis = rot.get("Axis", {})
                    setattr(
                        obj,
                        prop,
                        App.Placement(
                            App.Vector(pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)),
                            App.Rotation(
                                App.Vector(axis.get("x", 0), axis.get("y", 0), axis.get("z", 1)),
                                rot.get("Angle", 0),
                            ),
                        ),
                    )
                elif isinstance(getattr(obj, prop), App.Vector) and isinstance(val, dict):
                    setattr(obj, prop, App.Vector(val.get("x", 0), val.get("y", 0), val.get("z", 0)))
                elif prop in ("Base", "Tool", "Source", "Profile") and isinstance(val, str):
                    ref = doc.getObject(val)
                    if ref is None:
                        raise ValueError(f"Referenced object '{val}' not found.")
                    setattr(obj, prop, ref)
                elif prop == "References" and isinstance(val, list):
                    refs = []
                    for ref_name, face in val:
                        ref = doc.getObject(ref_name)
                        if ref is None:
                            raise ValueError(f"Referenced object '{ref_name}' not found.")
                        refs.append((ref, face))
                    setattr(obj, prop, refs)
                else:
                    setattr(obj, prop, val)
            elif prop == "ShapeColor" and isinstance(val, (list, tuple)):
                obj.ViewObject.ShapeColor = tuple(float(c) for c in val)
            elif prop == "ViewObject" and isinstance(val, dict):
                for key, sub in val.items():
                    if key == "ShapeColor":
                        obj.ViewObject.ShapeColor = tuple(float(c) for c in sub)
                    else:
                        setattr(obj.ViewObject, key, sub)
            else:
                setattr(obj, prop, val)
        except Exception as exc:
            App.Console.PrintError(f"Property '{prop}' assignment error: {exc}\n")


def _create_object(doc_name, obj_data):
    doc = App.getDocument(doc_name)
    if doc is None:
        raise ValueError(f"Document '{doc_name}' not found.")

    name = obj_data.get("Name", "New_Object")
    type_id = obj_data["Type"]
    analysis = obj_data.get("Analysis")
    properties = obj_data.get("Properties", {})

    if type_id == "Fem::FemMeshGmsh" and analysis:
        import ObjectsFem
        from femmesh.gmshtools import GmshTools

        obj = getattr(doc, analysis).addObject(ObjectsFem.makeMeshGmsh(doc, name))[0]
        _set_properties(doc, obj, properties)
        doc.recompute()
        GmshTools(obj).create_mesh()
    elif type_id.startswith("Fem::"):
        import ObjectsFem

        maker = getattr(ObjectsFem, f"make{type_id.split('::')[1]}", None)
        obj = maker(doc, name) if maker else doc.addObject(type_id, name)
        if analysis:
            getattr(doc, analysis).addObject(obj)
        _set_properties(doc, obj, properties)
    else:
        obj = doc.addObject(type_id, name)
        _set_properties(doc, obj, properties)

    doc.recompute()
    return obj.Name


class AgentRPC:
    """XML-RPC 對外介面。"""

    # --- 舊有 freecad-mcp 相容方法（簽章與回傳格式不可更動） ---

    def ping(self):
        return True

    def create_document(self, name="New_Document"):
        def task():
            doc = App.newDocument(name)
            doc.recompute()
            return doc.Name

        try:
            return {"success": True, "document_name": on_gui(task)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def create_object(self, doc_name, obj_data):
        try:
            return {"success": True, "object_name": on_gui(_create_object, doc_name, obj_data)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def edit_object(self, doc_name, obj_name, properties):
        def task():
            doc = App.getDocument(doc_name)
            if doc is None:
                raise ValueError(f"Document '{doc_name}' not found.")
            obj = doc.getObject(obj_name)
            if obj is None:
                raise ValueError(f"Object '{obj_name}' not found in document '{doc_name}'.")
            _set_properties(doc, obj, properties.get("Properties", properties))
            doc.recompute()
            return obj_name

        try:
            return {"success": True, "object_name": on_gui(task)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def delete_object(self, doc_name, obj_name):
        def task():
            doc = App.getDocument(doc_name)
            if doc is None:
                raise ValueError(f"Document '{doc_name}' not found.")
            doc.removeObject(obj_name)
            doc.recompute()
            return obj_name

        try:
            return {"success": True, "object_name": on_gui(task)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def execute_code(self, code):
        buffer = io.StringIO()

        def task():
            with contextlib.redirect_stdout(buffer):
                exec(code, _exec_globals)
            return True

        try:
            on_gui(task)
            return {
                "success": True,
                "message": "Python code execution scheduled. \nOutput: " + buffer.getvalue(),
            }
        except Exception as exc:
            return {"success": False, "error": f"{exc}\nOutput: {buffer.getvalue()}"}

    def execute_code_async(self, code):
        """排入執行但不等結果 — 給長時間運算用。"""
        _requests.put((lambda: exec(code, _exec_globals), False))
        return {"success": True, "message": "Python code queued for execution."}

    # 序列化會讀到 ViewObject，而 FreeCAD 1.2 起 GUI API 只准在主執行緒用，
    # 所以這兩個看似唯讀的方法也得排到 GUI 執行緒。
    def get_objects(self, doc_name):
        def task():
            doc = App.getDocument(doc_name)
            return [serialize.serialize_object(obj) for obj in doc.Objects] if doc else []

        return on_gui(task)

    def get_object(self, doc_name, obj_name):
        def task():
            doc = App.getDocument(doc_name)
            return serialize.serialize_object(doc.getObject(obj_name)) if doc else None

        return on_gui(task)

    def list_documents(self):
        return list(App.listDocuments().keys())

    def reload_document(self, doc_name):
        def task():
            doc = App.getDocument(doc_name)
            if doc is None:
                raise ValueError(f"Document '{doc_name}' not found.")
            path = doc.FileName
            if not path:
                raise ValueError(f"Document '{doc_name}' has never been saved.")
            App.closeDocument(doc.Name)
            return App.openDocument(path).Name

        try:
            return {"success": True, "document_name": on_gui(task)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_parts_list(self):
        try:
            from .parts_library import get_parts_list

            return get_parts_list()
        except Exception:
            return []

    def insert_part_from_library(self, relative_path):
        try:
            from .parts_library import insert_part_from_library

            on_gui(insert_part_from_library, relative_path)
            return {"success": True, "message": "Part inserted from library."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_active_screenshot(self, view_name="Isometric", width=None, height=None, focus_object=None):
        try:
            shots = on_gui(
                tools.capture,
                views=[str(view_name).lower()],
                width=width or 800,
                height=height or 600,
                focus=focus_object,
            )
            return shots[0]["png_base64"] if shots else None
        except Exception as exc:
            App.Console.PrintWarning(f"[AgentCAD] 截圖失敗：{exc}\n")
            return None

    def run_fem_analysis(self, doc_name, analysis_name, solver_name=None):
        def task():
            from femtools import ccxtools

            doc = App.getDocument(doc_name)
            if doc is None:
                raise ValueError(f"Document '{doc_name}' not found.")
            analysis = doc.getObject(analysis_name)
            if analysis is None:
                raise ValueError(f"Analysis '{analysis_name}' not found.")
            fea = ccxtools.FemToolsCcx(analysis, doc.getObject(solver_name) if solver_name else None)
            fea.update_objects()
            fea.setup_working_dir()
            fea.reset_all()
            fea.run()
            return [o.Name for o in analysis.Group if "Result" in o.Name]

        try:
            return {"success": True, "results": on_gui(task)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # --- AgentCAD 擴充能力 ---

    def list_tools(self):
        """回傳全部可用工具與說明，讓 AI 自行探索。"""
        out = []
        for name in sorted(TOOL_NAMES):
            func = getattr(tools, name)
            out.append({"name": name, "doc": (func.__doc__ or "").strip()})
        return out


# 這兩個是內部輔助函式，回傳 FreeCAD 物件，沒辦法經由 XML-RPC 傳出去。
NOT_TOOLS = frozenset(["get_doc", "resolve"])

# tools 模組裡其餘的公開函式，全部自動變成 RPC 方法。
TOOL_NAMES = [
    name
    for name in dir(tools)
    if not name.startswith("_")
    and name not in NOT_TOOLS
    and callable(getattr(tools, name))
    and getattr(getattr(tools, name), "__module__", None) == tools.__name__
]


def _bind_tools(rpc, server):
    for name in TOOL_NAMES:
        func = getattr(tools, name)
        server.register_function(
            (lambda f: lambda *a, **kw: _envelope(f, *a, **kw))(func),
            name,
        )
    server.register_instance(rpc, allow_dotted_names=False)


class _LocalOnlyServer(SimpleXMLRPCServer):
    """預設只收本機連線；要開遠端得自己在偏好設定打開。"""

    allow_reuse_address = True

    def __init__(self, addr, allowed, **kwargs):
        super().__init__(addr, **kwargs)
        self.allowed = allowed  # ip_network 清單

    def verify_request(self, request, client_address):
        try:
            ip = ipaddress.ip_address(client_address[0])
        except ValueError:
            return False
        return any(ip in net for net in self.allowed)


def _allowed_networks():
    params = settings()
    if not params.GetBool("AllowRemote", False):
        return [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]
    raw = params.GetString("AllowedIPs", "127.0.0.1")
    nets = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            App.Console.PrintWarning(f"[AgentCAD] 略過無效的 IP 設定：{token}\n")
    return nets or [ipaddress.ip_network("127.0.0.0/8")]


def start(port=None):
    """啟動 RPC 伺服器。重複呼叫是安全的。"""
    global _server, _thread
    if _server is not None:
        return f"AgentCAD RPC 已在 port {_server.server_address[1]} 執行中"

    params = settings()
    port = int(port or params.GetInt("Port", DEFAULT_PORT))
    host = "0.0.0.0" if params.GetBool("AllowRemote", False) else "127.0.0.1"

    _server = _LocalOnlyServer(
        (host, port),
        _allowed_networks(),
        allow_none=True,
        logRequests=False,
    )
    _bind_tools(AgentRPC(), _server)

    _thread = threading.Thread(target=_server.serve_forever, daemon=True, name="AgentCAD-RPC")
    _thread.start()
    start_pump()
    App.Console.PrintMessage(f"[AgentCAD] RPC 伺服器已啟動：{host}:{port}\n")
    return f"AgentCAD RPC 已啟動於 {host}:{port}"


def stop():
    global _server, _thread
    if _server is None:
        return "AgentCAD RPC 沒有在執行"
    _server.shutdown()
    _server.server_close()
    _server = None
    if _thread is not None:
        _thread.join(timeout=2)
        _thread = None
    App.Console.PrintMessage("[AgentCAD] RPC 伺服器已停止\n")
    return "AgentCAD RPC 已停止"


def is_running():
    return _server is not None


def status():
    return {
        "running": is_running(),
        "port": _server.server_address[1] if _server else settings().GetInt("Port", DEFAULT_PORT),
        "tools": len(TOOL_NAMES),
    }
