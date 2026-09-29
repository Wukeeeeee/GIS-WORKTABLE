# -*- coding: utf-8 -*-
"""GeoSource 内嵌服务与工具测试集。

验证：
1. 本地 gis_services.db 连接与路径解析
2. 基础统计（服务数、图层数、分类、协议、国家）
3. 多维度搜索（关键词、国家、协议、类别、免费/免Key筛选）
4. 服务详情与子图层提取
5. 只读 SQL 执行与安全拦截
6. LangChain @tool 工具调用
7. FastAPI HTTP 端点集成
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services import geosource_service as gs
from backend.services import tools as T
from backend.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_db_path_and_connection():
    """验证数据库路径存在且能正常连接。"""
    path = gs.get_db_path()
    assert os.path.exists(path), f"数据库文件不存在: {path}"
    conn = gs.get_db_connection(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM master")
        cnt = cur.fetchone()[0]
        assert cnt >= 2000, f"master 表服务数量异常: {cnt}"
    finally:
        conn.close()


def test_list_categories_and_stats():
    """验证统计总览数据。"""
    stats = gs.list_categories_and_stats()
    assert stats["total_services"] >= 2000
    assert stats["total_layers"] >= 1000
    assert len(stats["top_categories"]) > 0
    assert len(stats["top_protocols"]) > 0
    assert len(stats["top_countries"]) > 0


def test_search_services_by_keyword():
    """按关键词检索服务。"""
    res = gs.search_services(keyword="DEM", limit=5)
    assert res["total_returned"] > 0
    assert len(res["results"]) <= 5
    for r in res["results"]:
        assert "service_id" in r
        assert "service_name" in r
        assert "protocol" in r


def test_search_services_by_filters():
    """按国家和协议组合筛选。"""
    res = gs.search_services(country="中国", limit=10)
    assert res["total_returned"] > 0
    for r in res["results"]:
        assert "中国" in (r.get("country") or "") or "中国" in (r.get("region") or "")


def test_get_service_detail():
    """获取指定服务详情及图层列表。"""
    # 先搜索获取一个有效 ID
    search_res = gs.search_services(limit=1)
    assert search_res["total_returned"] > 0
    first_id = search_res["results"][0]["service_id"]

    detail = gs.get_service_detail(first_id)
    assert "error" not in detail
    assert detail["service_id"] == first_id
    assert "layers" in detail
    assert isinstance(detail["layers"], list)

    # 查不存在的 ID
    not_found = gs.get_service_detail("NON_EXISTENT_ID_99999")
    assert "error" in not_found


def test_query_sql_safe_execution():
    """验证安全 SELECT 查询与破坏性语句拦截。"""
    # 正常 SELECT
    res = gs.query_sql("SELECT service_id, service_name FROM master LIMIT 3")
    assert "error" not in res
    assert res["row_count"] == 3

    # 非法写入拦截
    bad_res1 = gs.query_sql("DROP TABLE master")
    assert "error" in bad_res1
    assert "只读" in bad_res1["error"]

    bad_res2 = gs.query_sql("DELETE FROM master")
    assert "error" in bad_res2


def test_langchain_tools():
    """验证 LangGraph/LangChain @tool 工具。"""
    # 1. 概况工具
    stats_out = T.get_gis_services_stats.invoke({})
    assert "全球 GIS 空间服务库统计" in stats_out
    assert "空间服务总数" in stats_out

    # 2. 检索工具
    search_out = T.search_gis_services.invoke({"query": "卫星", "limit": 3})
    assert "找到" in search_out or "未找到" in search_out

    # 3. 详情工具
    detail_out = T.get_gis_service_detail.invoke({"service_id": "WMS-0001"})
    assert "WMS-0001" in detail_out or "服务详情" in detail_out or "未找到" in detail_out


def test_fastapi_geosource_endpoints(client):
    """验证 FastAPI REST 接口响应。"""
    # GET /api/geosource/stats
    r_stats = client.get("/api/geosource/stats")
    assert r_stats.status_code == 200
    data_stats = r_stats.json()
    assert data_stats["total_services"] >= 2000

    # POST /api/geosource/search (分页验证)
    r_search = client.post("/api/geosource/search", json={"keyword": "高程", "page": 1, "page_size": 5})
    assert r_search.status_code == 200
    data_search = r_search.json()
    assert "results" in data_search
    assert "total" in data_search
    assert "total_pages" in data_search
    assert data_search["page"] == 1
    assert len(data_search["results"]) <= 5

    # GET /api/geosource/service/{id}
    if data_search["results"]:
        sid = data_search["results"][0]["service_id"]
        r_det = client.get(f"/api/geosource/service/{sid}")
        assert r_det.status_code == 200
        assert r_det.json()["service_id"] == sid

    # POST /api/geosource/query-sql
    r_sql = client.post("/api/geosource/query-sql", json={"query": "SELECT count(*) as c FROM layers"})
    assert r_sql.status_code == 200
    assert r_sql.json()["rows"][0]["c"] >= 1000

    # GET /api/geosource/proxy (非法 URL 拦截测试)
    r_proxy_bad = client.get("/api/geosource/proxy?url=invalid_url")
    assert r_proxy_bad.status_code == 400
