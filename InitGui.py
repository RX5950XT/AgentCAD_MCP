# SPDX-License-Identifier: LGPL-2.1-or-later
"""AgentCAD —— 為 AI agent 而生的 3D 建模環境。

FreeCAD 執行完這個檔案就會丟掉它的全域命名空間，所以這裡只做一件事：
把工作台交給 agentcad.workbench 註冊，實際邏輯全部住在 package 裡。
"""

from agentcad import workbench

workbench.register()
