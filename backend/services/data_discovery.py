"""GIS 开放数据发现与获取 —— Discovery / Download 门面层。

职责（严格区分，不写进一个巨大函数）：
  1. Data Discovery（搜索）：解析需求 → 选择候选 Provider → 返回各数据源元信息；
  2. Data Download（获取）：调用 Provider 获取数据；
  3. Data Import（导入）：storage 统一落盘(GIS 文件)、完整性校验、CRS 保留、metadata。

由确定性的程序代码完成；AI 只负责把自然语言解析成结构化参数后调用本层。
"""

from __future__ import annotations

import os
from typing import Optional

from backend.services.data_providers import storage
from backend.services.data_providers.base import (
    get_registry,
    list_capabilities,
    provider_by_id,
)
from backend.services.data_providers.errors import (
    DataProviderError,
    DataValidationError,
)
from backend.services.data_providers.models import (
    ALL_KINDS,
    DataRequest,
    DataType,
    DownloadedAsset,
    normalize_format,
    normalize_kind,
    parse_bbox,
    sanitize_name,
)

VECTOR_KIND_DEFAULT_FMT = "geojson"
RASTER_KIND_DEFAULT_FMT = "geotiff"


# ============================================================
# 需求解析（把上层解析后的字符串参数规整为 DataRequest）
# ============================================================

def resolve_request(*, query: str = "", kind: str = "", area: str = "",
                    bbox: str = "", provider_id: str = "", file_format: str = "",
                    time_start: str = "", time_end: str = "",
                    max_items: int = 0, out_dir: Optional[str] = None) -> DataRequest:
    """规整/校验结构化参数；缺关键信息抛 DataProviderError（带明确中文提示）。"""
    nkind = normalize_kind(kind, query)
    if not nkind:
        from backend.services.data_providers.models import ALL_KINDS as _K
        raise DataProviderError(
            "无法识别要获取的数据类型（kind）。",
            hint=f"请指定要素类型：{', '.join(f'{k}({v})' for k, v in _K.items())}",
        )
    bb = parse_bbox(bbox)
    area_txt = (area or "").strip()
    if not area_txt and not bb:
        raise DataProviderError(
            "缺少空间范围：请提供城市/区域名（area，如 长沙市）或经纬度 bbox。",
            hint="bbox 格式：minLng,minLat,maxLng,maxLat。",
        )
    if bb and area_txt:
        # 都给了以 bbox 为准（更精确）
        pass
    pid = (provider_id or "").strip().lower()

    if file_format:
        nfmt = normalize_format(file_format)
        if not nfmt:
            raise DataProviderError(
                f"不支持的文件格式「{file_format}」。",
                hint="矢量支持 geojson/gpkg/shp；栅格支持 geotiff。",
            )
    else:
        nfmt = RASTER_KIND_DEFAULT_FMT if nkind in ("imagery", "dem", "landcover") \
            else VECTOR_KIND_DEFAULT_FMT

    return DataRequest(
        kind=nkind,
        area=area_txt,
        bbox=tuple(bb) if bb else None,
        provider_id=pid,
        query=(query or "").strip(),
        time_start=(time_start or "").strip(),
        time_end=(time_end or "").strip(),
        file_format=nfmt,
        max_items=int(max_items or 0),
        out_dir=out_dir,
    )


def _candidate_providers(kind: str, provider_id: str = ""):
    """返回候选 Provider 实例列表。

    provider_id 为空时按能力自动选（公开优先）。
    provider_id 指向不存在或能力不匹配 → 抛明确错误。
    """
    registry = get_registry()
    if provider_id:
        p = provider_by_id(provider_id)
        if p is None:
            raise DataProviderError(
                f"未知数据源 provider='{provider_id}'。",
                hint="可用数据源：" + ", ".join(c["name"] for c in list_capabilities()),
            )
        if not p.supports(kind):
            cap = p.capability()
            raise DataProviderError(
                f"数据源 {cap.name} 不支持该类型（{ALL_KINDS.get(kind, kind)}）。",
                hint=f"{cap.name} 支持：矢量 {cap.vector_kinds}；栅格 {cap.raster_kinds}。",
            )
        return [p]
    return registry.capable_providers(kind)


# ============================================================
# Data Discovery —— 搜索/发现
# ============================================================

def discover(*, query: str = "", kind: str = "", area: str = "", bbox: str = "",
             provider_id: str = "", file_format: str = "", time_start: str = "",
             time_end: str = "", max_items: int = 0) -> dict:
    """返回结构化发现结果 dict（含各 Provider 命中 / 指引 / 错误，不静默）。"""
    req = resolve_request(
        query=query, kind=kind, area=area, bbox=bbox, provider_id=provider_id,
        file_format=file_format, time_start=time_start, time_end=time_end,
        max_items=max_items,
    )
    providers = _candidate_providers(req.kind, req.provider_id)

    hits, notes = [], []
    for p in providers:
        try:
            res = p.search(req)
            items = res if isinstance(res, list) else [res]
            items = [it for it in items if it is not None]
            hits.extend(items)
            if items:
                # 能力层面提示一条来源即可
                if p.capability().note:
                    notes.append({"provider": p.provider_id, "level": "info", "message": p.capability().note})
        except DataProviderError as e:
            notes.append({
                "provider": p.provider_id,
                "level": "auth" if e.__class__.__name__ == "ProviderAuthError" else "error",
                "message": e.message,
                "hint": e.hint,
            })
    # 命中去重（按 title+provider）
    seen, uniq = set(), []
    for h in hits:
        key = (h.provider_id, h.title)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)

    return {
        "ok": bool(uniq),
        "kind": req.kind,
        "kind_label": ALL_KINDS.get(req.kind, req.kind),
        "area": req.area or (f"bbox {bbox}" if bbox else ""),
        "data_type": _kind_data_type(req.kind),
        "hits": [h.to_dict() for h in uniq[:50]],
        "notes": notes,
        "message": _discover_summary(uniq, notes, req),
    }


def _kind_data_type(kind: str) -> str:
    from backend.services.data_providers.models import RASTER_KINDS
    return DataType.RASTER if kind in RASTER_KINDS else DataType.VECTOR


def _discover_summary(hits: list, notes: list, req: DataRequest) -> str:
    lines = []
    if hits:
        vh = [h for h in hits if h.data_type == DataType.VECTOR and h.downloadable]
        if vh:
            first = vh[0]
            lines.append(
                f"{req.area or '指定范围'} 的「{ALL_KINDS.get(req.kind, req.kind)}」可从 "
                f"{first.provider} 获取（Provider={first.provider_id}）。"
            )
        else:
            lines.append("找到遥感/地形目录元信息；该类下载需要账号，尚未自动启用。")
    if notes:
        lines.append("数据源说明：")
        lines.extend(f"- {n['message']}" + (f"（{n['hint']}）" if n.get('hint') else "") for n in notes)
    return "\n".join(lines) if lines else "未找到可用数据。"


# ============================================================
# Data Download + Import —— 获取 → GIS 文件 → metadata
# ============================================================

def download(*, query: str = "", kind: str = "", area: str = "", bbox: str = "",
             provider_id: str = "", file_format: str = "", time_start: str = "",
             time_end: str = "", max_items: int = 0, layer_name: str = "",
             out_dir: Optional[str] = None) -> dict:
    """获取数据并落盘为 GIS 文件（含完整性/CRS 校验 + metadata）。

    成功返回 DownloadedAsset dict；失败抛 DataProviderError 明确子类。
    """
    req = resolve_request(
        query=query, kind=kind, area=area, bbox=bbox, provider_id=provider_id,
        file_format=file_format, time_start=time_start, time_end=time_end,
        max_items=max_items, out_dir=out_dir,
    )
    # 下载需要一个确定的 Provider
    provider = _single_download_provider(req)
    cap = provider.capability()
    raw = provider.download(req)  # 可能是 {geojson,...} 矢量

    data_type = provider.data_type_of(req.kind)
    if data_type == DataType.VECTOR:
        asset = _import_vector(req, provider, raw, cap, layer_name)
    elif data_type == DataType.RASTER:
        asset = _import_raster(req, provider, raw, cap, layer_name)
    else:
        raise DataProviderError(f"Provider {cap.name} 未声明该类型的数据类型。")
    return asset.to_dict()


def _single_download_provider(req: DataRequest):
    candidates = _candidate_providers(req.kind, req.provider_id)
    if req.provider_id:
        return candidates[0]
    # 未显式指定：矢量只有一个公开源(OSM)；栅格需显式选择（遥感下载均需账号）
    vector = [p for p in candidates if p.data_type_of(req.kind) == DataType.VECTOR]
    if vector:
        return vector[0]
    names = "、".join(p.capability().name for p in candidates)
    raise DataProviderError(
        "栅格/遥感数据自动下载第一阶段未启用（多个数据源均需账号）。",
        hint=f"请先 discover 查看候选（{names}）的元信息；遥感影像获取属下一阶段。",
    )


def _import_vector(req, provider, raw, cap, layer_name) -> DownloadedAsset:
    geojson = raw.get("geojson")
    if not isinstance(geojson, dict):
        raise DataValidationError(
            f"数据源 {cap.name} 未返回可用的 GeoJSON。", provider=provider.provider_id)
    crs = raw.get("crs") or cap.crs_default or "EPSG:4326"
    crs_known = bool(raw.get("crs_known", True))
    # 未知 CRS / 空数据在此明确拒绝（不允许加载未知数据）
    fc = storage.validate_vector(geojson, provider=cap.name, crs=crs, crs_known=crs_known)

    area = req.area or _bbox_name(req.bbox)
    auto_name = sanitize_name(f"{area}_{req.kind}")
    asset_name = sanitize_name(layer_name) if (layer_name or "").strip() else auto_name
    dirpath = req.out_dir or storage.asset_dir(provider.provider_id)

    path = storage.write_vector(
        fc, out_format=req.file_format, name=asset_name, dirpath=dirpath,
        crs=crs, crs_known=crs_known,
    )
    size = storage.file_size(path)
    geom_types = raw.get("geometry_types") or storage.geom_types_of(fc)
    bbox = raw.get("bbox") or storage.compute_bbox(fc)

    meta = storage.build_metadata(
        provider=provider.provider_id, provider_name=cap.name, kind=req.kind,
        area=area, source_url=cap.homepage, file_path=path,
        file_format=req.file_format, crs=crs, crs_known=crs_known,
        size_bytes=size, feature_count=len(fc.get("features", [])),
        geometry_types=geom_types, bbox=bbox, query=req.query, auth=cap.auth,
        note=("截断提示：" if raw.get("truncated") else "") + cap.note,
    )
    meta_path = storage.save_metadata(meta, dirpath=dirpath, name=asset_name)
    meta["metadata_file"] = os.path.basename(meta_path)

    note = "（要素超出单次上限，已按上限截断）" if raw.get("truncated") else ""
    return DownloadedAsset(
        provider=provider.provider_id,
        provider_name=cap.name,
        kind=req.kind,
        kind_label=ALL_KINDS.get(req.kind, req.kind),
        data_type=DataType.VECTOR,
        layer_name=asset_name,
        title=f"{area}-{ALL_KINDS.get(req.kind, req.kind)}",
        area=area,
        file_path=path,
        url=storage.to_download_url(path),
        file_format=req.file_format,
        crs=crs,
        crs_known=crs_known,
        size_bytes=size,
        feature_count=len(fc.get("features", [])),
        geometry_types=geom_types,
        bbox=bbox,
        geojson=fc,
        metadata=meta,
        note=note,
    )


def _import_raster(req, provider, raw, cap, layer_name) -> DownloadedAsset:
    # 第一阶段栅格不自动获取（auth Provider 的 download 已抛错）。
    raise DataProviderError(
        f"数据源 {cap.name} 未返回可导入的栅格文件（第一阶段遥感不自动下载）。",
        provider=provider.provider_id,
        hint="请先 discover 查看元信息，再通过手动上传 GeoTIFF 加载。",
    )


def _bbox_name(bbox: Optional[tuple]) -> str:
    if not bbox:
        return "范围"
    return sanitize_name(",".join(str(round(v, 4)) for v in bbox))


# ============================================================
# 对外：能力列表
# ============================================================

def sources() -> dict:
    caps = list_capabilities()
    return {
        "count": len(caps),
        "sources": caps,
        "note": "auth=public 免认证；api_key 需配置 Key(环境变量)；account 需账号登录，均不硬编码。",
    }
