# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD 零件庫存取（沿用 freecad-mcp 的行為，維持相容）。"""

import os
from functools import cache

import FreeCAD
import FreeCADGui


def _library_path():
    return os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "parts_library")


def insert_part_from_library(relative_path):
    part_path = os.path.join(_library_path(), relative_path)
    if not os.path.exists(part_path):
        raise FileNotFoundError(f"Not found: {part_path}")
    FreeCADGui.ActiveDocument.mergeProject(part_path)


@cache
def get_parts_list():
    root_path = _library_path()
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Not found: {root_path}")

    parts = []
    for root, _, files in os.walk(root_path):
        for name in files:
            if name.endswith(".FCStd"):
                parts.append(os.path.relpath(os.path.join(root, name), root_path))
    return parts
