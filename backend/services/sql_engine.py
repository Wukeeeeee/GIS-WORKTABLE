# -*- coding: utf-8 -*-
"""GIS WorkTable — 安全只读空间与属性 SQL 执行引擎 (SQL Engine)

能力：
1. 内存动态挂载：将当前内存中所有已注册的 GeoJSON 图层（_registered_layers）
   自动转为 SQLite 内存表，要素属性（properties）转为数据列，
   并保留 _geom_json / _fid 等空间列。
2. 安全约束：仅允许 SELECT / WITH / EXPLAIN，并由 SQLite 只读模式拒绝写操作。
3. 自动图层衍生 (Query to Layer)：
   若查询结果包含有效的几何要素（_geom_json），自动组装为标准 GeoJSON 并可推送到地图。
4. 属性报表输出：自动格式化为整齐的 Markdown 表格输出。
"""

import json
import sqlite3
import re
import time
from typing import Dict, Any, Tuple

SQL_QUERY_TIMEOUT_SECONDS = 10.0
SQL_MAX_RESULT_ROWS = 100_000
SQL_MAX_RESULT_BYTES = 32 * 1024 * 1024
SQL_MAX_VALUE_BYTES = 16 * 1024 * 1024


def is_safe_readonly_sql(sql: str) -> Tuple[bool, str]:
    """严格校验 SQL 是否为纯只读查询"""
    clean = (sql or "").strip()
    if not clean:
        return False, "SQL 语句不能为空"

    # 去掉多行注释和单行注释。
    # 修复：原实现对整串做正则替换，会误伤字符串字面量里的 "--"/"/*"（如
    # WHERE note = '--说明' 会被截断  查询条件静默失效）。
    # 逐字符扫描并跳过字符串与引用标识符，仅移除引用区域外的注释。
    def _strip_sql_comments(s: str) -> str:
        out = []
        i, n = 0, len(s)
        while i < n:
            ch = s[i]
            if ch in ("'", '"', "`", "["):
                quote = "]" if ch == "[" else ch
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
                out.append(" ")
                i = n if j == -1 else j + 2
            elif s.startswith("--", i):
                j = s.find("\n", i)
                out.append(" ")
                i = n if j == -1 else j + 1
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    clean_no_comments = _strip_sql_comments(clean)
    first_token = re.match(r"([A-Za-z]+)\b", clean_no_comments.lstrip())
    if not first_token:
        return False, "SQL 语句无效"

    first_word = first_token.group(1).upper()
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return False, f"仅支持执行 SELECT 或 WITH 只读查询，拒绝执行「{first_word}」语句"

    # 禁止破坏性关键词
    forbidden = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
        "ATTACH", "DETACH", "CREATE", "REPLACE", "GRANT", "REVOKE",
        "PRAGMA", "VACUUM", "BEGIN", "COMMIT", "ROLLBACK"
    ]
    # 关键字黑名单只检查 SQL 语法部分，避免字符串/引用标识符中的词被误判。
    def _strip_quoted_regions(s: str) -> str:
        out = []
        i, n = 0, len(s)
        while i < n:
            ch = s[i]
            if ch in ("'", '"', "`"):
                quote = ch
                i += 1
                while i < n:
                    if s[i] == quote:
                        if i + 1 < n and s[i + 1] == quote:
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                out.append(" ")
            elif ch == "[":
                i += 1
                while i < n:
                    if s[i] == "]":
                        if i + 1 < n and s[i + 1] == "]":
                            i += 2
                            continue
                        i += 1
                        break
                    i += 1
                out.append(" ")
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    upper_sql = f" {_strip_quoted_regions(clean_no_comments).upper()} "
    for word in forbidden:
        pattern = rf"\b{word}\b"
        if word == "REPLACE":
            # SQLite's REPLACE(...) scalar function is read-only.
            pattern += r"(?!\s*\()"
        if re.search(pattern, upper_sql):
            return False, f"检测到破坏性或写操作关键字「{word}」，已拦截"

    return True, ""


def execute_layer_sql(sql: str, registered_layers: dict,
                      create_result_layer: bool = True) -> Dict[str, Any]:
    """在内存中对当前所有图层执行只读 SQL 查询。

    Args:
        sql: 用户或 AI 编写的只读 SQL
        registered_layers: tools._registered_layers 字典
        create_result_layer: 若结果含几何，是否生成新图层

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
    query_timed_out = False
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
            if _safe_base.casefold() in _used_table_names:
                import hashlib as _hl
                _hash_tag = _hl.md5(layer_name.encode("utf-8")).hexdigest()[:6]
                table_name = f"{_safe_base[:40]}_{_hash_tag}"
                suffix = 2
                while table_name.casefold() in _used_table_names:
                    table_name = f"{_safe_base[:40]}_{_hash_tag}_{suffix}"
                    suffix += 1
            else:
                table_name = _safe_base
            _used_table_names.add(table_name.casefold())

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
            # SQLite 允许引用数字开头的标识符；列名中的双引号需重复转义。
            safe_cols = []
            for col in field_list:
                safe_col = '"' + col.replace('"', '""') + '"'
                # No column affinity: preserve JSON numbers as SQLite numbers,
                # rather than turning numeric comparisons and MAX into text operations.
                safe_cols.append(safe_col)

            cols_def = ", ".join(safe_cols)
            if cols_def:
                cols_def = ", " + cols_def

            create_sql = f'CREATE TABLE "{table_name}" (_fid TEXT, _geom_json TEXT{cols_def});'
            cur.execute(create_sql)

            # 插入数据
            insert_rows = []
            for idx, f in enumerate(features):
                props = f.get("properties") or {}
                fid = f.get("id")
                if fid is None:
                    fid = props.get("_fid")
                if fid is None:
                    fid = idx
                fid = str(fid)
                geom = f.get("geometry") or {}
                geom_str = json.dumps(geom, ensure_ascii=False) if geom else ""

                row_vals = [fid, geom_str]
                for col in field_list:
                    val = props.get(col)
                    if isinstance(val, (dict, list)):
                        val = json.dumps(val, ensure_ascii=False)
                    elif val is not None and not isinstance(val, (str, int, float)):
                        val = str(val)
                    row_vals.append(val)
                insert_rows.append(row_vals)

            if insert_rows:
                placeholders = ", ".join(["?"] * (2 + len(field_list)))
                insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
                cur.executemany(insert_sql, insert_rows)

        # 2. 执行用户查询
        cur.execute("PRAGMA query_only = ON")
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_MAX_VALUE_BYTES)
        deadline = time.monotonic() + SQL_QUERY_TIMEOUT_SECONDS

        def interrupt_expired_query():
            nonlocal query_timed_out
            query_timed_out = time.monotonic() >= deadline
            return int(query_timed_out)

        conn.set_progress_handler(interrupt_expired_query, 1000)
        cur.execute(sql)
        rows_raw = []
        result_bytes = 0
        for row in cur:
            result_bytes += sum(
                len(value.encode("utf-8")) if isinstance(value, str)
                else len(value) if isinstance(value, bytes) else 8
                for value in row
            )
            if result_bytes > SQL_MAX_RESULT_BYTES or len(rows_raw) >= SQL_MAX_RESULT_ROWS:
                return {
                    "ok": False,
                    "error": (f"SQL 结果超过 {SQL_MAX_RESULT_ROWS:,} 行或 "
                              f"{SQL_MAX_RESULT_BYTES // (1024 * 1024)} MB，"
                              "请使用 WHERE、聚合或 LIMIT 缩小结果。"),
                    "row_count": 0, "rows": [], "markdown_table": "",
                }
            rows_raw.append(row)
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
            "error": (f"SQL 查询超过 {SQL_QUERY_TIMEOUT_SECONDS:g} 秒，已中断，请缩小查询范围。"
                      if query_timed_out else f"SQL 执行异常: {str(e)}"),
            "row_count": 0,
            "rows": [],
            "markdown_table": ""
        }
    finally:
        conn.close()
