# -*- coding: utf-8 -*-
"""GIS WorkTable — 安全只读空间与属性 SQL 执行引擎 (SQL Engine)

能力：
1. 内存动态挂载：将当前内存中所有已注册的 GeoJSON 图层（_registered_layers）
   自动转为 SQLite 内存表，要素属性（properties）转为数据列，
   并保留 _geom_geojson / _fid 等空间列。
2. 安全约束：严格白名单只读查询（仅允许 SELECT / WITH），硬拦截一切破坏性关键词。
3. 自动图层衍生 (Query to Layer)：
   若查询结果包含有效的几何要素（_geom_geojson），自动组装为标准 GeoJSON 并可推送到地图。
4. 属性报表输出：自动格式化为整齐的 Markdown 表格输出。
"""

import json
import sqlite3
import re
from typing import Dict, Any, List, Optional, Tuple


def is_safe_readonly_sql(sql: str) -> Tuple[bool, str]:
    """严格校验 SQL 是否为纯只读查询"""
    clean = (sql or "").strip()
    if not clean:
        return False, "SQL 语句不能为空"

    # 去掉多行注释和单行注释。
    # 修复：原实现对整串做正则替换，会误伤字符串字面量里的 "--"/"/*"（如
    # WHERE note = '--说明' 会被截断  查询条件静默失效）。
    # 现改为逐字符扫描、跳过 '..' 与 ".." 字面量内部，仅移除字面量外的注释。
    def _strip_sql_comments(s: str) -> str:
        out = []
        i, n = 0, len(s)
        while i < n:
            ch = s[i]
            if ch in ("'", '"'):
                quote = ch
                j = i + 1
                while j < n:
                    if s[j] == quote:
                        if j + 1 < n and s[j + 1] == quote:  # 转义的引号 ''
                            j += 2
                            continue
                        break
                    j += 1
                out.append(s[i:j + 1])
                i = j + 1
            elif s.startswith("/*", i):
                j = s.find("*/", i + 2)
                i = n if j == -1 else j + 2
            elif s.startswith("--", i):
                j = s.find("\n", i)
                i = n if j == -1 else j + 1
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    clean_no_comments = _strip_sql_comments(clean)
    tokens = clean_no_comments.strip().split()
    if not tokens:
        return False, "SQL 语句无效"

    first_word = tokens[0].upper()
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return False, f"仅支持执行 SELECT 或 WITH 只读查询，拒绝执行「{first_word}」语句"

    # 禁止破坏性关键词
    forbidden = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "ATTACH", "DETACH", "CREATE", "REPLACE", "GRANT", "REVOKE",
        "PRAGMA", "VACUUM", "BEGIN", "COMMIT", "ROLLBACK"
    ]
    upper_sql = f" {clean_no_comments.upper()} "
    for word in forbidden:
        if re.search(rf"\b{word}\b", upper_sql):
            return False, f"检测到破坏性或写操作关键字「{word}」，已拦截"

    return True, ""


def execute_layer_sql(sql: str, registered_layers: dict,
                      create_result_layer: bool = True,
                      result_layer_name: str = "") -> Dict[str, Any]:
    """在内存中对当前所有图层执行只读 SQL 查询。

    Args:
        sql: 用户或 AI 编写的只读 SQL
        registered_layers: tools._registered_layers 字典
        create_result_layer: 若结果含几何，是否生成新图层
        result_layer_name: 衍生新图层的名称

    Returns:
        {
            "ok": bool,
            "row_count": int,
            "columns": [...],
            "rows": [...],
            "markdown_table": str,
            "derived_geojson": Optional[dict],
            "error": Optional[str]
        }
    """
    safe, err_msg = is_safe_readonly_sql(sql)
    if not safe:
        return {"ok": False, "error": err_msg, "row_count": 0, "rows": []}

    # 创建隔离的纯内存数据库
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # 1. 动态将每个图层挂载为内存表
        _used_table_names = set()
        for layer_name, layer_data in registered_layers.items():
            geojson = layer_data.get("geojson") or (layer_data if isinstance(layer_data, dict) else {})
            features = geojson.get("features", [])
            if not features and geojson.get("type") == "Feature":
                features = [geojson]

            # 清理表名（只保留合法字符）。保持「图层名 sanitize 后 = 表名」的对外约定
            # （AI/用户按该名字写 FROM）。仅当多个图层 sanitize 后撞名时，对后来者
            # 追加 6 位短 hash 后缀保唯一，防止 "A-B"/"A B" 数据混入同一表。
            _safe_base = re.sub(r"[^\w\u4e00-\u9fa5]", "_", layer_name)
            if not _safe_base:
                continue
            if _safe_base in _used_table_names:
                import hashlib as _hl
                _hash_tag = _hl.md5(layer_name.encode("utf-8")).hexdigest()[:6]
                table_name = f"{_safe_base[:40]}_{_hash_tag}"
            else:
                table_name = _safe_base
            _used_table_names.add(table_name)

            # 探测所有 properties 字段名
            all_fields = set()
            for f in features:
                props = f.get("properties") or {}
                all_fields.update(props.keys())

            # _fid and _geom_json are reserved engine columns. SQLite resolves
            # identifiers case-insensitively, so their property aliases must be
            # filtered case-insensitively as well. _fid is already
            # materialized from the feature id (or the injected property), and
            # _geom_json is populated from geometry; duplicating either source
            # property in the CREATE TABLE statement causes duplicate-column
            # errors for otherwise valid layers.
            reserved_fields = {"_fid", "_geom_json"}
            field_list = []
            fields_by_folded_name = {}
            for field in sorted(all_fields, key=lambda value: (str(value).casefold(), str(value))):
                if not isinstance(field, str):
                    return {
                        "ok": False,
                        "error": f"图层「{layer_name}」包含非文本字段名，无法用于 SQL 查询",
                        "row_count": 0, "rows": [], "markdown_table": "",
                    }
                folded_name = field.casefold()
                if folded_name in reserved_fields:
                    continue
                previous = fields_by_folded_name.get(folded_name)
                if previous is not None and previous != field:
                    return {
                        "ok": False,
                        "error": f"图层「{layer_name}」包含大小写冲突字段「{previous}」和「{field}」，SQLite 查询无法区分它们",
                        "row_count": 0, "rows": [], "markdown_table": "",
                    }
                fields_by_folded_name[folded_name] = field
                field_list.append(field)
            # 过滤掉以数字开头的非法列名
            safe_cols = []
            for col in field_list:
                safe_col = f'"{col}"'
                safe_cols.append(f"{safe_col} TEXT")

            cols_def = ", ".join(safe_cols)
            if cols_def:
                cols_def = ", " + cols_def

            create_sql = f'CREATE TABLE "{table_name}" (_fid TEXT, _geom_json TEXT{cols_def});'
            cur.execute(create_sql)

            # 插入数据
            insert_rows = []
            for idx, f in enumerate(features):
                props = f.get("properties") or {}
                fid = str(f.get("id") or props.get("_fid") or idx)
                geom = f.get("geometry") or {}
                geom_str = json.dumps(geom, ensure_ascii=False) if geom else ""

                row_vals = [fid, geom_str]
                for col in field_list:
                    val = props.get(col)
                    row_vals.append(str(val) if val is not None else None)
                insert_rows.append(row_vals)

            if insert_rows:
                placeholders = ", ".join(["?"] * (2 + len(field_list)))
                insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
                cur.executemany(insert_sql, insert_rows)

        # 2. 执行用户查询
        cur.execute(sql)
        rows_raw = cur.fetchall()
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = [dict(r) for r in rows_raw]

        # 3. 检查是否可衍生为新图层 (Query to Layer)
        derived_geojson = None
        has_geom = "_geom_json" in columns
        if has_geom and create_result_layer and rows:
            out_features = []
            for r in rows:
                g_str = r.get("_geom_json")
                if g_str:
                    try:
                        g_obj = json.loads(g_str)
                        if g_obj and g_obj.get("type"):
                            # 把除了 _geom_json 之外的列保留在 properties
                            props = {k: v for k, v in r.items() if k != "_geom_json"}
                            out_features.append({
                                "type": "Feature",
                                "geometry": g_obj,
                                "properties": props
                            })
                    except Exception:
                        pass
            if out_features:
                derived_geojson = {
                    "type": "FeatureCollection",
                    "features": out_features
                }

        # 4. 生成可读的 Markdown 表格输出
        # 去掉内部字段以供表格阅读
        display_cols = [c for c in columns if c != "_geom_json"]
        lines = []
        if display_cols and rows:
            lines.append("| " + " | ".join(display_cols) + " |")
            lines.append("| " + " | ".join(["---"] * len(display_cols)) + " |")
            for r in rows[:50]:  # 最多预览 50 行
                row_str = " | ".join([str(r.get(c, "") if r.get(c) is not None else "") for c in display_cols])
                lines.append(f"| {row_str} |")
            if len(rows) > 50:
                lines.append(f"\n*(共 {len(rows)} 条记录，以上展示前 50 条)*")

        md_table = "\n".join(lines) if lines else "查询成功，返回 0 条记录。"

        return {
            "ok": True,
            "row_count": len(rows),
            "columns": columns,
            "rows": rows,
            "markdown_table": md_table,
            "derived_geojson": derived_geojson,
            "error": None
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"SQL 执行异常: {str(e)}",
            "row_count": 0,
            "rows": [],
            "markdown_table": ""
        }
    finally:
        conn.close()
