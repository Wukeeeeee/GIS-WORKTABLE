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
import os
import re
import tempfile
import uuid
import time
from typing import Any, Dict, List, Optional, Tuple


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
             depends_on: List[str] = None) -> Dict:
    """创建新的 Node 对象"""
    return {
        "id": node_id,
        "type": "tool",
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


def save_workflow(wf: Dict, file_path: str) -> bool:
    """持久化保存 Workflow 到文件 (.giswork / .json)"""
    try:
        directory = os.path.dirname(os.path.abspath(file_path))
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".workflow-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(wf, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, file_path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        return True
    except Exception as e:
        print(f"[Workflow] 保存工作流失败: {e}", flush=True)
        return False


def load_workflow(file_path: str) -> Optional[Dict]:
    """从文件加载 Workflow 对象"""
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Workflow] 加载工作流失败: {e}", flush=True)
        return None


def materialize_from_history(task_id: str, workflow_name: str = "") -> Optional[Dict]:
    """从真实执行历史中物化生成可复现的 DAG 工作流。
    
    自动分析历史执行记录：
    1. 提取 task_id 关联的所有成功工具调用；
    2. 基于输入/输出图层名自动建立节点间拓扑依赖 (depends_on 与 ${node_id.output})；
    3. 生成标准的 Workflow DAG 对象。
    """
    from backend.services import history_service
    entries = history_service.get_entries_by_task(task_id, only_ok=True)
    if not entries:
        return None

    wf_name = workflow_name or f"任务_{task_id[:8]}_分析工作流"
    nodes = []
    layer_producers = {}  # layer_name -> (node_id, output_key)

    for idx, e in enumerate(entries):
        node_id = f"node_{idx + 1}"
        tool_name = e.get("tool", "")
        raw_args = dict(e.get("args", {}))
        depends_on = []

        # 检查参数中引用的图层是否由上游节点生成
        def _process_arg_val(val: Any, is_sql: bool = False, param_key: str = "") -> Any:
            if isinstance(val, str):
                # 1. 优先尝试直接匹配上游图层名
                if not is_sql and val in layer_producers:
                    dep_node, output_key = layer_producers[val]
                    if dep_node not in depends_on:
                        depends_on.append(dep_node)
                    return f"${{{dep_node}.{output_key}}}"
                # 2. 针对显式图层列表参数或各分项均为主管图层的逗号分隔字符串
                is_layer_list_param = param_key in ("layers", "layer_names", "layer_ids", "source_layers", "input_layers")
                if not is_sql and "," in val:
                    parts = [p.strip() for p in val.split(",")]
                    if parts and (is_layer_list_param or all(p in layer_producers for p in parts if p)):
                        new_parts = []
                        for p in parts:
                            if p in layer_producers:
                                dep_node, output_key = layer_producers[p]
                                if dep_node not in depends_on:
                                    depends_on.append(dep_node)
                                new_parts.append(f"${{{dep_node}.{output_key}}}")
                            else:
                                new_parts.append(p)
                        return ",".join(new_parts)
                # 3. 针对 SQL 语句中的图层表名引用
                if is_sql or ("SELECT" in val.upper() and "FROM" in val.upper()):
                    new_val = val
                    for layer in sorted(layer_producers.keys(), key=len, reverse=True):
                        dep_node, output_key = layer_producers[layer]
                        quoted = f'"{layer}"'
                        if quoted in new_val:
                            if dep_node not in depends_on:
                                depends_on.append(dep_node)
                            new_val = new_val.replace(quoted, f'"${{{dep_node}.{output_key}}}"')
                        elif re.search(rf'\bFROM\s+{re.escape(layer)}\b', new_val, flags=re.IGNORECASE) or \
                             re.search(rf'\bJOIN\s+{re.escape(layer)}\b', new_val, flags=re.IGNORECASE):
                            if dep_node not in depends_on:
                                depends_on.append(dep_node)
                            new_val = re.sub(rf'\b({re.escape(layer)})\b', f"${{{dep_node}.{output_key}}}", new_val)
                    return new_val
                return val
            elif isinstance(val, list):
                return [_process_arg_val(item, is_sql=is_sql, param_key=param_key) for item in val]
            elif isinstance(val, dict):
                return {k: _process_arg_val(v, is_sql=(k == "sql"), param_key=k) for k, v in val.items()}
            return val

        inputs = {k: _process_arg_val(v, is_sql=(k == "sql"), param_key=k) for k, v in raw_args.items()}

        node = new_node(
            node_id=node_id,
            name=f"{tool_name}_{idx + 1}",
            tool=tool_name,
            inputs=inputs,
            depends_on=depends_on,
        )

        # 记录本节点产出的图层名（供后续节点建立依赖）
        out_layer_list = [str(out_layer) for out_layer in e.get("layer_ids", []) if out_layer]
        for output_index, out_layer in enumerate(out_layer_list):
            output_key = "layer_name" if output_index == 0 else f"layer_name_{output_index + 1}"
            layer_producers[out_layer] = (node_id, output_key)
            node["outputs"][output_key] = out_layer
            node["outputs"][f"layer_name_{output_index + 1}"] = out_layer
        if len(out_layer_list) > 1:
            node["outputs"]["layer_names"] = out_layer_list

        # 若参数里显式指定了输出图层名（排除输入图层名如 layer_name, target_layer, name）
        for arg_key in ("result_layer_name", "output_layer_name", "output_name", "output_layer", "result_layer"):
            out_name = raw_args.get(arg_key)
            if isinstance(out_name, str) and out_name.strip():
                clean_out_name = out_name.strip()
                node["outputs"].setdefault("layer_name", clean_out_name)
                layer_producers.setdefault(clean_out_name, (node_id, "layer_name"))

        nodes.append(node)

    wf = new_workflow(
        name=wf_name,
        description=f"由任务 {task_id} 实际执行历史自动提炼物化的 DAG 工作流，包含 {len(nodes)} 个执行节点。",
        nodes=nodes
    )
    return wf


# ============================================================
# Schema 校验
# ============================================================

def validate_workflow(wf: Dict, available_tools: List[str]) -> List[str]:
    """校验 Workflow 结构，返回错误列表（空列表表示通过）"""
    errors = []

    if not isinstance(wf, dict):
        return ["Workflow 必须是对象"]

    if not isinstance(wf.get("name"), str) or not wf["name"].strip():
        errors.append("Workflow 缺少 name 字段")

    nodes = wf.get("nodes", [])
    if not isinstance(nodes, list):
        return errors + ["Workflow 的 nodes 字段必须是列表"]
    if not nodes:
        errors.append("Workflow 没有任何节点")
        return errors

    node_ids = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"节点 {i} 必须是对象")
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not nid.strip():
            errors.append(f"节点 {i} 缺少有效的 id")
            continue
        if nid in node_ids:
            errors.append(f"节点 id 重复: {nid}")
        node_ids.add(nid)

        if not isinstance(node.get("name"), str) or not node["name"].strip():
            errors.append(f"节点 {nid} 缺少有效的 name 字段")

        if not isinstance(node.get("tool"), str) or not node["tool"].strip():
            errors.append(f"节点 {nid} 缺少 tool 字段")
        elif node["tool"] not in available_tools:
            errors.append(f"节点 {nid} 的工具不存在: {node['tool']}")

        if not isinstance(node.get("inputs", {}), dict):
            errors.append(f"节点 {nid} 的 inputs 字段必须是对象")
        if not isinstance(node.get("outputs", {}), dict):
            errors.append(f"节点 {nid} 的 outputs 字段必须是对象")

        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, list):
            errors.append(f"节点 {nid} 的 depends_on 字段必须是列表")

        if node.get("type", "tool") != "tool":
            errors.append(f"节点 {nid} 的类型暂不支持: {node['type']}（仅支持 tool）")

        if node.get("status") and (
            not isinstance(node["status"], str) or node["status"] not in NODE_STATUSES
        ):
            errors.append(f"节点 {nid} 的状态非法: {node['status']}")

    # 检查依赖
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id", "")
        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, list):
            continue
        for dep in dependencies:
            if not isinstance(dep, str) or not dep:
                errors.append(f"节点 {nid} 的依赖标识必须是非空字符串")
                continue
            if dep not in node_ids:
                errors.append(f"节点 {nid} 依赖不存在的节点: {dep}")

    # 循环依赖检测
    if not errors:
        cycle = _detect_cycle(nodes)
        if cycle:
            errors.append(f"检测到循环依赖: {' -> '.join(cycle)}")

    return errors


def _detect_cycle(nodes: List[Dict]) -> Optional[List[str]]:
    """检测 DAG 中的循环依赖（Kahn 拓扑）；检测到环返回环上受影响的节点列表，否则返回 None。

    比 DFS 回溯稳：不用 parent 回溯，能处理多汇聚点/重边，保证终止。
    """
    valid_nodes = [n for n in nodes if isinstance(n, dict) and n.get("id")]
    graph = {n["id"]: list(n.get("depends_on", [])) for n in valid_nodes}
    # 只能走依赖存在的边，防悬空 dep
    node_ids = set(graph.keys())
    for nid in graph:
        graph[nid] = [d for d in graph[nid] if d in node_ids]

    in_degree = {nid: 0 for nid in graph}
    reverse = {nid: [] for nid in graph}
    for nid, deps in graph.items():
        in_degree[nid] = len(deps)
        for dep in deps:
            reverse[dep].append(nid)

    # Kahn：持续弹出 in_degree=0 的节点。若结束时还有节点剩下来，就存在环
    stack = [nid for nid, deg in in_degree.items() if deg == 0]
    visited_count = 0
    while stack:
        u = stack.pop()
        visited_count += 1
        for v in reverse[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                stack.append(v)

    if visited_count == len(graph):
        return None

    # 返回仍在环/受环影响的节点列表（in_degree > 0）
    cycle_nodes = [nid for nid, deg in in_degree.items() if deg > 0]
    return cycle_nodes or None


# ============================================================
# 拓扑排序
# ============================================================

def topological_sort(nodes: List[Dict]) -> List[str]:
    """返回节点执行顺序（拓扑排序）"""
    valid_nodes = [n for n in nodes if isinstance(n, dict) and n.get("id")]
    node_ids = {n["id"] for n in valid_nodes}
    graph = {n["id"]: [d for d in n.get("depends_on", []) if d in node_ids] for n in valid_nodes}
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

def _tool_failure_message(result: Any) -> Optional[str]:
    """将工具返回的显式失败也标记为失败，避免只因返回了字符串就显示成功。"""
    if isinstance(result, dict):
        status = str(result.get("status", "")).strip().lower()
        if (result.get("ok") is False or result.get("success") is False
                or result.get("is_error") is True
                or status in {"error", "failed", "failure"}):
            return str(result.get("error") or result.get("message") or "工具明确返回失败状态")
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    msg = _tool_failure_message(payload)
                    if msg:
                        return msg
            except Exception:
                pass
        failure_prefixes = (
            "工具执行失败:", "执行失败:", "工作流执行失败:", "Workflow 执行失败:",
            "失败:", "失败：", "错误:", "错误：", "异常:", "异常：",
        )
        if text.startswith(failure_prefixes):
            return text
        first_line = text.splitlines()[0][:100] if text else ""
        if re.match(r"^(?:失败|错误|异常)[:：]", first_line) or re.match(r"^[^\s:：]{1,30}(?:失败|错误|异常)[:：]", first_line):
            return text
        if any(marker in first_line for marker in ("失败:", "失败：", "未通过:", "未通过：", "异常:", "异常：")):
            return text
        if any(marker in text.lower() for marker in ("状态: failed", "状态：failed", "status: failed")):
            return text
    return None

class WorkflowExecutor:
    """Workflow 执行引擎，调用现有 Tool Registry"""

    def __init__(self, tool_registry: Dict, register_layer_fn=None,
                 event_callback=None, failure_detector=None, layer_snapshot_fn=None):
        """
        tool_registry: {tool_name: tool_function}
        register_layer_fn: 注册图层的回调函数(name, geojson) -> None
        event_callback: 事件回调函数(event_dict) -> None，用于 SSE 推送
        failure_detector: 可选工具级失败判定器，签名为 (tool_name, result) -> bool
        layer_snapshot_fn: 返回 {layer_name: registration_token}，用于暴露工具副作用产生的图层
        """
        self.tool_registry = tool_registry
        self.register_layer_fn = register_layer_fn
        self.event_callback = event_callback
        self.failure_detector = failure_detector
        self.layer_snapshot_fn = layer_snapshot_fn

    def _emit(self, event: Dict):
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception:
                pass

    def execute(self, wf: Dict) -> Dict:
        """执行整个 Workflow，返回更新后的 Workflow 对象"""
        if not isinstance(wf, dict):
            return {
                "id": None, "name": "", "nodes": [], "status": "failed",
                "error": "Workflow 必须是对象",
            }
        errors = validate_workflow(wf, list(self.tool_registry))
        if errors:
            wf["status"] = "failed"
            wf["error"] = "; ".join(errors)
            for node in wf.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                node_id = node.get("id")
                node_errors = [error for error in errors if node_id and f"节点 {node_id} " in error]
                if node_errors:
                    node["status"] = "failed"
                    node["error"] = "; ".join(node_errors)[:500]
                    self._emit({
                        "type": "workflow_node_failed", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": node["error"],
                    })
                else:
                    node["status"] = "skipped"
                    node["error"] = "工作流结构校验未通过，节点未执行"
                    self._emit({
                        "type": "workflow_node_skipped", "node_id": node_id,
                        "name": node.get("name", ""), "tool": node.get("tool", ""),
                        "error": node["error"],
                    })
            self._emit({
                "type": "workflow_failed",
                "workflow_id": wf.get("id"),
                "error": wf["error"],
            })
            return wf

        # 重置所有节点的输出、错误、状态与执行计时，防止重跑时残留旧状态
        for node in wf["nodes"]:
            node["outputs"] = {}
            node["error"] = None
            node["status"] = "pending"
            node["duration"] = None
            node.pop("_started_ts", None)
            node.pop("_finished_ts", None)
            node.pop("started_at", None)
            node.pop("finished_at", None)

        if not isinstance(wf.get("id"), str) or not wf["id"].strip():
            wf["id"] = f"wf_{uuid.uuid4().hex[:12]}"
        wf["error"] = None
        wf["status"] = "running"
        wf["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._emit({"type": "workflow_started", "workflow_id": wf["id"], "name": wf["name"]})

        # 拓扑排序
        order = topological_sort(wf["nodes"])
        node_map = {n["id"]: n for n in wf["nodes"]}

        for nid in order:
            node = node_map[nid]

            # 检查上游是否有未成功节点
            upstream_not_ok = any(
                node_map[dep].get("status") != "success"
                for dep in node.get("depends_on", [])
                if dep in node_map
            )
            if upstream_not_ok:
                node["status"] = "skipped"
                node["error"] = "上游节点未执行成功，跳过执行"
                self._emit({
                    "type": "workflow_node_skipped", "node_id": nid,
                    "name": node["name"], "tool": node["tool"], "error": node["error"],
                })
                continue

            # 收集上游输出
            upstream_outputs = {}
            for dep in node.get("depends_on", []):
                if dep in node_map:
                    dep_node = node_map[dep]
                    upstream_outputs[dep] = dep_node.get("outputs", {})

            # 执行节点（内部另存 ms 级 _started_ts 供 duration 精确计算）
            node["status"] = "running"
            node["_started_ts"] = time.time()
            node["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._emit({
                "type": "workflow_node_started",
                "node_id": nid,
                "name": node["name"],
                "tool": node["tool"],
            })

            try:
                layers_before = self.layer_snapshot_fn() if self.layer_snapshot_fn else {}
                result = self._execute_node(node, upstream_outputs)
                failure = _tool_failure_message(result)
                if failure is None and self.failure_detector:
                    try:
                        if self.failure_detector(node["tool"], result):
                            failure = str(result)[:500] or "工具返回失败状态"
                    except Exception:
                        pass
                if failure:
                    raise RuntimeError(failure)
                outputs = result if isinstance(result, dict) else {"result": result}
                if self.layer_snapshot_fn:
                    layers_after = self.layer_snapshot_fn()
                    changed_layers = [
                        name for name, token in layers_after.items()
                        if layers_before.get(name) != token
                    ]
                    if len(changed_layers) == 1:
                        outputs.setdefault("layer_name", changed_layers[0])
                        outputs.setdefault("layer_name_1", changed_layers[0])
                    elif changed_layers:
                        outputs.setdefault("layer_name", changed_layers[0])
                        outputs.setdefault("layer_names", changed_layers)
                        for i, l_name in enumerate(changed_layers):
                            outputs.setdefault(f"layer_name_{i + 1}", l_name)
                node["outputs"] = outputs
                node["status"] = "success"
                node["_finished_ts"] = time.time()
                node["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                # 用内部 ts 计算 duration（毫秒精度），显示字段保持字符串
                _st = node.get("_started_ts")
                _ft = node.get("_finished_ts")
                if isinstance(_st, (int, float)) and isinstance(_ft, (int, float)):
                    node["duration"] = round(_ft - _st, 3)
                else:
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
                node["_finished_ts"] = time.time()
                node["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _st = node.get("_started_ts")
                _ft = node.get("_finished_ts")
                if isinstance(_st, (int, float)) and isinstance(_ft, (int, float)):
                    node["duration"] = round(_ft - _st, 3)
                else:
                    node["duration"] = None
                self._emit({
                    "type": "workflow_node_failed",
                    "node_id": nid,
                    "name": node["name"],
                    "error": node["error"],
                })

        # 最终状态
        failed = [n for n in wf["nodes"] if n["status"] == "failed"]
        skipped = [n for n in wf["nodes"] if n["status"] == "skipped"]
        pending = [n for n in wf["nodes"] if n["status"] == "pending"]
        if failed:
            wf["status"] = "failed"
            wf["error"] = f"{len(failed)} 个节点失败"
        elif skipped:
            wf["status"] = "partial"
            wf["error"] = f"{len(skipped)} 个节点被跳过"
        elif pending:
            wf["status"] = "partial"
            wf["error"] = f"{len(pending)} 个节点未执行"
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

        tool = self.tool_registry[tool_name]
        inputs = dict(node.get("inputs", {}))

        # 解析上游输出引用：格式为 "${node_id.output_key}"
        resolved = self._resolve_inputs(inputs, upstream_outputs)

        # LangChain StructuredTool 必须通过 invoke 调用；普通 Python 函数继续兼容。
        invoke = getattr(tool, "invoke", None)
        if callable(invoke):
            result = invoke(resolved)
        elif callable(tool):
            result = tool(**resolved)
        else:
            raise TypeError(f"工具注册项不可执行: {tool_name}")
        return result

    def _resolve_inputs(self, inputs: Dict, upstream_outputs: Dict) -> Dict:
        """解析输入中的上游引用 ${node_id.key}，支持递归解析字典、列表、空白容错、嵌套属性及字符串插值"""
        def _get_nested_val(data: Any, path: str) -> Tuple[bool, Any]:
            if not path:
                return True, data
            if isinstance(data, dict) and path in data:
                return True, data[path]
            curr = data
            for part in path.split("."):
                part = part.strip()
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                elif isinstance(curr, (list, tuple)) and part.isdigit() and int(part) < len(curr):
                    curr = curr[int(part)]
                else:
                    return False, None
            return True, curr

        def _resolve_ref(ref_str: str) -> Any:
            ref = ref_str.strip()
            if "." in ref:
                dep_id, out_path = [x.strip() for x in ref.split(".", 1)]
                if dep_id not in upstream_outputs:
                    raise ValueError(f"输入引用 ${{{ref}}} 未声明对应 depends_on")
                ok, val = _get_nested_val(upstream_outputs[dep_id], out_path)
                if not ok:
                    raise ValueError(f"上游节点 {dep_id} 未产生输出 {out_path}")
                return val
            else:
                dep_id = ref
                if dep_id not in upstream_outputs:
                    raise ValueError(f"输入引用 ${{{ref}}} 未声明对应 depends_on")
                return upstream_outputs[dep_id]

        def _resolve_val(val: Any) -> Any:
            if isinstance(val, str):
                val_stripped = val.strip()
                m_single = re.fullmatch(r"\$\{\s*([^}]+)\s*\}", val_stripped)
                if m_single:
                    return _resolve_ref(m_single.group(1))
                elif "${" in val:
                    def _replace_match(m):
                        res = _resolve_ref(m.group(1))
                        return "" if res is None else str(res)
                    return re.sub(r"\$\{\s*([^}]+)\s*\}", _replace_match, val)
                return val
            elif isinstance(val, list):
                return [_resolve_val(item) for item in val]
            elif isinstance(val, dict):
                return {k: _resolve_val(v) for k, v in val.items()}
            return val

        resolved = {}
        for key, val in inputs.items():
            resolved[key] = _resolve_val(val)
        return resolved


    def _auto_register_layer(self, node: Dict):
        """如果节点输出包含 GeoJSON，自动注册为图层"""
        if not self.register_layer_fn:
            return
        outputs = node.get("outputs", {})
        # 支持直接返回 GeoJSON，或将其包在 geojson/其他输出字段中的工具。
        geojson = outputs if outputs.get("type") in ("FeatureCollection", "Feature") else next(
            (value for value in outputs.values()
             if isinstance(value, dict) and value.get("type") in ("FeatureCollection", "Feature")),
            None,
        )
        if geojson is None:
            return
        layer_name = f"{node['name']}_结果"
        try:
            self.register_layer_fn(layer_name, geojson)
            outputs.setdefault("layer_name", layer_name)
        except Exception:
            pass
