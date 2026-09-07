# -*- coding: utf-8 -*-
"""
GIS Workflow 执行引擎
- DAG 拓扑排序 + 循环依赖检测
- 逐节点调用现有 Tool Registry
- 节点输出传递给下游
- 失败时停止依赖节点
- 结果自动注册为图层
"""
import json
import uuid
import time
from typing import Any, Dict, List, Optional


# ============================================================
# 数据模型
# ============================================================

NODE_STATUSES = {"pending", "running", "success", "failed", "skipped"}


def new_workflow(name: str, description: str = "", nodes: List[Dict] = None) -> Dict:
    """创建新的 Workflow 对象"""
    return {
        "id": f"wf_{uuid.uuid4().hex[:12]}",
        "name": name,
        "description": description,
        "status": "pending",
        "nodes": nodes or [],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": None,
    }


def new_node(node_id: str, name: str, tool: str, inputs: Dict = None,
             depends_on: List[str] = None, node_type: str = "tool") -> Dict:
    """创建新的 Node 对象"""
    return {
        "id": node_id,
        "type": node_type,  # tool / python / data
        "name": name,
        "tool": tool,
        "status": "pending",
        "inputs": inputs or {},
        "outputs": {},
        "depends_on": depends_on or [],
        "error": None,
        "started_at": None,
        "finished_at": None,
        "duration": None,
    }


# ============================================================
# Schema 校验
# ============================================================

def validate_workflow(wf: Dict, available_tools: List[str]) -> List[str]:
    """校验 Workflow 结构，返回错误列表（空列表表示通过）"""
    errors = []

    if not wf.get("name"):
        errors.append("Workflow 缺少 name 字段")

    nodes = wf.get("nodes", [])
    if not nodes:
        errors.append("Workflow 没有任何节点")
        return errors

    node_ids = set()
    for i, node in enumerate(nodes):
        nid = node.get("id")
        if not nid:
            errors.append(f"节点 {i} 缺少 id")
            continue
        if nid in node_ids:
            errors.append(f"节点 id 重复: {nid}")
        node_ids.add(nid)

        if not node.get("tool"):
            errors.append(f"节点 {nid} 缺少 tool 字段")
        elif node["tool"] not in available_tools:
            errors.append(f"节点 {nid} 的工具不存在: {node['tool']}")

        if node.get("status") and node["status"] not in NODE_STATUSES:
            errors.append(f"节点 {nid} 的状态非法: {node['status']}")

    # 检查依赖
    for node in nodes:
        nid = node.get("id", "")
        for dep in node.get("depends_on", []):
            if dep not in node_ids:
                errors.append(f"节点 {nid} 依赖不存在的节点: {dep}")

    # 循环依赖检测
    if not errors:
        cycle = _detect_cycle(nodes)
        if cycle:
            errors.append(f"检测到循环依赖: {' -> '.join(cycle)}")

    return errors


def _detect_cycle(nodes: List[Dict]) -> Optional[List[str]]:
    """检测 DAG 中的循环依赖，返回循环路径或 None"""
    graph = {n["id"]: n.get("depends_on", []) for n in nodes}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in graph}
    parent = {}

    def dfs(u):
        color[u] = GRAY
        for v in graph.get(u, []):
            if color[v] == GRAY:
                # 找到循环，回溯路径
                cycle = [v, u]
                cur = u
                while parent.get(cur) and parent[cur] != v:
                    cur = parent[cur]
                    cycle.append(cur)
                cycle.append(v)
                return list(reversed(cycle))
            if color[v] == WHITE:
                parent[v] = u
                result = dfs(v)
                if result:
                    return result
        color[u] = BLACK
        return None

    for nid in graph:
        if color[nid] == WHITE:
            result = dfs(nid)
            if result:
                return result
    return None


# ============================================================
# 拓扑排序
# ============================================================

def topological_sort(nodes: List[Dict]) -> List[str]:
    """返回节点执行顺序（拓扑排序）"""
    graph = {n["id"]: n.get("depends_on", []) for n in nodes}
    in_degree = {nid: len(deps) for nid, deps in graph.items()}
    # 反向图：dep -> [依赖它的节点]
    reverse = {nid: [] for nid in graph}
    for nid, deps in graph.items():
        for dep in deps:
            reverse[dep].append(nid)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    result = []
    while queue:
        u = queue.pop(0)
        result.append(u)
        for v in reverse[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
    return result


# ============================================================
# 执行引擎
# ============================================================

class WorkflowExecutor:
    """Workflow 执行引擎，调用现有 Tool Registry"""

    def __init__(self, tool_registry: Dict, register_layer_fn=None,
                 event_callback=None):
        """
        tool_registry: {tool_name: tool_function}
        register_layer_fn: 注册图层的回调函数(name, geojson) -> None
        event_callback: 事件回调函数(event_dict) -> None，用于 SSE 推送
        """
        self.tool_registry = tool_registry
        self.register_layer_fn = register_layer_fn
        self.event_callback = event_callback

    def _emit(self, event: Dict):
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception:
                pass

    def execute(self, wf: Dict) -> Dict:
        """执行整个 Workflow，返回更新后的 Workflow 对象"""
        wf["status"] = "running"
        wf["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._emit({"type": "workflow_started", "workflow_id": wf["id"], "name": wf["name"]})

        # 拓扑排序
        order = topological_sort(wf["nodes"])
        node_map = {n["id"]: n for n in wf["nodes"]}

        for nid in order:
            node = node_map[nid]

            # 检查上游是否有失败
            upstream_failed = any(
                node_map[dep].get("status") in ("failed", "skipped")
                for dep in node.get("depends_on", [])
            )
            if upstream_failed:
                node["status"] = "skipped"
                node["error"] = "上游节点失败，跳过执行"
                self._emit({"type": "workflow_node_skipped", "node_id": nid, "name": node["name"]})
                continue

            # 收集上游输出
            upstream_outputs = {}
            for dep in node.get("depends_on", []):
                dep_node = node_map[dep]
                upstream_outputs[dep] = dep_node.get("outputs", {})

            # 执行节点
            node["status"] = "running"
            node["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._emit({
                "type": "workflow_node_started",
                "node_id": nid,
                "name": node["name"],
                "tool": node["tool"],
            })

            try:
                result = self._execute_node(node, upstream_outputs)
                node["outputs"] = result if isinstance(result, dict) else {"result": result}
                node["status"] = "success"
                node["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if node["started_at"]:
                    try:
                        s = time.mktime(time.strptime(node["started_at"], "%Y-%m-%d %H:%M:%S"))
                        f = time.mktime(time.strptime(node["finished_at"], "%Y-%m-%d %H:%M:%S"))
                        node["duration"] = round(f - s, 2)
                    except Exception:
                        node["duration"] = None
                self._emit({
                    "type": "workflow_node_completed",
                    "node_id": nid,
                    "name": node["name"],
                    "status": "success",
                })

                # 自动注册图层
                self._auto_register_layer(node)

            except Exception as e:
                node["status"] = "failed"
                node["error"] = str(e)[:500]
                node["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._emit({
                    "type": "workflow_node_failed",
                    "node_id": nid,
                    "name": node["name"],
                    "error": node["error"],
                })

        # 最终状态
        failed = [n for n in wf["nodes"] if n["status"] == "failed"]
        skipped = [n for n in wf["nodes"] if n["status"] == "skipped"]
        if failed:
            wf["status"] = "failed"
            wf["error"] = f"{len(failed)} 个节点失败"
        elif skipped:
            wf["status"] = "partial"
            wf["error"] = f"{len(skipped)} 个节点被跳过"
        else:
            wf["status"] = "success"

        wf["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._emit({
            "type": "workflow_completed",
            "workflow_id": wf["id"],
            "status": wf["status"],
        })
        return wf

    def _execute_node(self, node: Dict, upstream_outputs: Dict) -> Any:
        """执行单个节点，调用现有工具"""
        tool_name = node["tool"]
        if tool_name not in self.tool_registry:
            raise ValueError(f"工具不存在: {tool_name}")

        tool_fn = self.tool_registry[tool_name]
        inputs = dict(node.get("inputs", {}))

        # 解析上游输出引用：格式为 "${node_id.output_key}"
        resolved = self._resolve_inputs(inputs, upstream_outputs)

        # 调用工具
        result = tool_fn(**resolved)
        return result

    def _resolve_inputs(self, inputs: Dict, upstream_outputs: Dict) -> Dict:
        """解析输入中的上游引用 ${node_id.key}"""
        resolved = {}
        for key, val in inputs.items():
            if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
                ref = val[2:-1]
                if "." in ref:
                    dep_id, out_key = ref.split(".", 1)
                    resolved[key] = upstream_outputs.get(dep_id, {}).get(out_key, val)
                else:
                    resolved[key] = upstream_outputs.get(ref, val)
            else:
                resolved[key] = val
        return resolved

    def _auto_register_layer(self, node: Dict):
        """如果节点输出包含 GeoJSON，自动注册为图层"""
        if not self.register_layer_fn:
            return
        outputs = node.get("outputs", {})
        # 检查输出是否是 GeoJSON
        for key, val in outputs.items():
            if isinstance(val, dict) and val.get("type") in ("FeatureCollection", "Feature"):
                layer_name = f"{node['name']}_结果"
                try:
                    self.register_layer_fn(layer_name, val)
                except Exception:
                    pass
                break
