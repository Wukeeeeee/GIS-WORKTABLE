# -*- coding: utf-8 -*-
"""GeoSource Service — 全球 GIS 空间服务与图层目录检索服务（内嵌版）。

基于本地 SQLite 索引（2,198+ 真实 GIS 服务、1,561+ 空间图层），
提供毫秒级搜索、协议筛选、服务详情获取及统计汇总。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Optional, Dict, Any

# 默认数据库路径：优先环境变量 GEOSOURCE_DB_PATH，其次 data/gis_services.db
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "data", "gis_services.db")


def get_db_path() -> str:
    r"""获取 gis_services.db 的实际绝对路径。
    自动检测策略：
    1. 环境变量 GEOSOURCE_DB_PATH
    2. 同级开发的 GeoSource 仓库（E:\my_repo\GeoSource\gis_services.db），若更新时间更新则优先使用
    3. 本地 data/gis_services.db
    """
    env_path = os.environ.get("GEOSOURCE_DB_PATH", "").strip()
    if env_path and os.path.exists(env_path):
        return os.path.abspath(env_path)

    local_path = _DEFAULT_DB_PATH if os.path.exists(_DEFAULT_DB_PATH) else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gis_services.db"
    )

    # 检查同级目录下的独立 GeoSource 仓库
    sibling_path = os.path.abspath(os.path.join(_REPO_ROOT, "..", "GeoSource", "gis_services.db"))
    if os.path.exists(sibling_path):
        # 如果同级 GeoSource 的数据库存在且更新时间更晚，优先使用最新的 GeoSource 数据
        if not os.path.exists(local_path) or os.path.getmtime(sibling_path) >= os.path.getmtime(local_path):
            return sibling_path

    if os.path.exists(local_path):
        return local_path
    if os.path.exists(sibling_path):
        return sibling_path
    return _DEFAULT_DB_PATH


def get_db_connection(readonly: bool = False) -> sqlite3.Connection:
    """创建并返回 SQLite 连接。"""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"GeoSource 数据库未找到: {db_path}，请确认已放置 gis_services.db")
    if readonly:
        # URI 模式只读打开（路径转义：兼容含 ?、%、空格、中文的 db 路径）
        from urllib.parse import quote as _urlquote
        uri = f"file:{_urlquote(os.path.abspath(db_path).replace(chr(92), '/'))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def search_services(
    keyword: Optional[str] = None,
    country: Optional[str] = None,
    protocol: Optional[str] = None,
    category: Optional[str] = None,
    is_free: Optional[bool] = None,
    need_no_key: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    """多条件检索全球 GIS 空间服务（支持分页与全量检索）。

    Args:
        keyword: 关键词（匹配服务名、描述、机构提供者、备注或类别）
        country: 国家或地区（如 '中国', '美国', 'Global', '德国', '日本'）
        protocol: GIS 服务协议（如 'WMS', 'WFS', 'XYZ', 'WMTS', 'REST', 'STAC', 'CKAN'）
        category: 数据类别（如 '高程/地形', '交通', '气象', '人口', '开放政府数据', '土地利用', '水利/海洋'）
        is_free: 是否免费服务
        need_no_key: 是否免 API Key（无需配置密钥即可直接用）
        page: 当前页码（从 1 开始）
        page_size: 每页条数（默认 20，最大 100）
        limit: 限制返回条数（兼容老接口，若指定且未指定 page 则单页截断）
    """
    keyword = (keyword or "").strip() or None
    country = (country or "").strip() or None
    protocol = (protocol or "").strip() or None
    category = (category or "").strip() or None

    conn = get_db_connection(readonly=True)
    cur = conn.cursor()

    conditions = []
    params = []

    if keyword:
        kw = f"%{keyword.strip()}%"
        conditions.append(
            "(service_name LIKE ? OR data_description LIKE ? OR provider LIKE ? OR notes LIKE ? OR category LIKE ?)"
        )
        params.extend([kw, kw, kw, kw, kw])

    if country:
        conditions.append("(country LIKE ? OR region LIKE ?)")
        params.extend([f"%{country.strip()}%", f"%{country.strip()}%"])

    if protocol:
        conditions.append("protocol LIKE ?")
        params.append(f"%{protocol.strip()}%")

    if category:
        conditions.append("category LIKE ?")
        params.append(f"%{category.strip()}%")

    if is_free is not None:
        val = "是" if is_free else "否"
        conditions.append("(free = ? OR is_free = ?)")
        params.extend([val, val])

    if need_no_key is not None:
        val = "是" if need_no_key else "否"
        conditions.append("need_no_key = ?")
        params.append(val)

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    # 计算总匹配条数
    count_sql = f"SELECT COUNT(*) FROM master {where_clause}"
    try:
        cur.execute(count_sql, list(params))
        total_count = cur.fetchone()[0]
    except Exception:
        conn.close()
        raise

    # 分页参数计算
    if limit is not None and limit > 0:
        actual_limit = min(limit, 100)
        actual_offset = max(0, (page - 1) * actual_limit)
        actual_page_size = actual_limit
    else:
        actual_page_size = min(max(1, page_size), 100)
        actual_page = max(1, page)
        actual_offset = (actual_page - 1) * actual_page_size
        actual_limit = actual_page_size

    total_pages = max(1, (total_count + actual_page_size - 1) // actual_page_size) if total_count > 0 else 1
    current_page = max(1, page)

    sql = f"""
        SELECT 
            service_id, service_name, country, region, provider, category, protocol,
            service_url, official_url, docs_url, is_free, need_no_key, format,
            spatial_coverage, status, data_description, crs
        FROM master
        {where_clause}
        ORDER BY 
            CASE WHEN status = '已验证' THEN 1 WHEN status = '未验证' THEN 2 ELSE 3 END,
            service_id
        LIMIT ? OFFSET ?
    """
    query_params = list(params) + [actual_limit, actual_offset]

    try:
        cur.execute(sql, query_params)
        rows = cur.fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    results = [dict(r) for r in rows]
    return {
        "total": total_count,
        "page": current_page,
        "page_size": actual_page_size,
        "total_pages": total_pages,
        "total_returned": len(results),
        "results": results
    }


def get_service_detail(service_id: str) -> Dict[str, Any]:
    """获取指定服务 ID 的完整元数据及其下属图层列表。"""
    sid = (service_id or "").strip()
    if not sid:
        return {"error": "缺少 service_id 参数"}

    with closing(get_db_connection(readonly=True)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM master WHERE service_id = ?", (sid,))
        service_row = cur.fetchone()

        if not service_row:
            return {"error": f"未找到 ID 为 '{sid}' 的服务。"}

        service_data = dict(service_row)
        cur.execute(
            "SELECT layer_idx, layer_name FROM layers WHERE service_id = ? ORDER BY layer_idx",
            (sid,)
        )
        layer_rows = cur.fetchall()

    service_data["layers"] = [dict(lr) for lr in layer_rows]
    return service_data


_last_db_mtime = 0.0
_cached_stats_data = None


def list_categories_and_stats() -> Dict[str, Any]:
    """获取 GeoSource 数据源库全貌统计信息：总数、主流分类、协议及国家覆盖（根据 DB 修改时间智能缓存）。"""
    global _last_db_mtime, _cached_stats_data
    db_path = get_db_path()
    try:
        current_mtime = os.path.getmtime(db_path)
    except Exception:
        current_mtime = 0.0

    if (
        _cached_stats_data is not None
        and db_path == _cached_stats_data.get("db_path")
        and current_mtime == _last_db_mtime
    ):
        return dict(_cached_stats_data)

    with closing(get_db_connection(readonly=True)) as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM master")
        total_services = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM layers")
        total_layers = cur.fetchone()[0]

        cur.execute(
            "SELECT category, count(*) as count FROM master WHERE category != '' GROUP BY category ORDER BY count DESC LIMIT 15"
        )
        top_categories = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT protocol, count(*) as count FROM master WHERE protocol != '' GROUP BY protocol ORDER BY count DESC LIMIT 10"
        )
        top_protocols = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT country, count(*) as count FROM master WHERE country != '' GROUP BY country ORDER BY count DESC LIMIT 20"
        )
        top_countries = [dict(r) for r in cur.fetchall()]

    _cached_stats_data = {
        "total_services": total_services,
        "total_layers": total_layers,
        "top_categories": top_categories,
        "top_protocols": top_protocols,
        "top_countries": top_countries,
        "db_path": db_path
    }
    _last_db_mtime = current_mtime
    return dict(_cached_stats_data)


def query_sql(query: str) -> Dict[str, Any]:
    """执行针对 GeoSource 数据库的安全只读 SELECT 查询。"""
    clean_query = (query or "").strip()
    clean_upper = clean_query.upper()
    if not clean_upper.startswith("SELECT") and not clean_upper.startswith("WITH"):
        return {"error": "仅允许执行 SELECT 或 WITH 只读查询。"}

    # 禁止破坏性关键词
    forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "ATTACH", "DETACH"]
    for word in forbidden:
        if f" {word} " in f" {clean_upper} ":
            return {"error": f"不允许在只读查询中包含 '{word}' 关键字。"}

    conn = get_db_connection(readonly=True)
    cur = conn.cursor()
    try:
        cur.execute(clean_query)
        rows = cur.fetchmany(101)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        results = [dict(zip(columns, r)) for r in rows[:100]]
        return {
            "row_count": len(results),
            "rows": results,
            "truncated": len(rows) > 100,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()
