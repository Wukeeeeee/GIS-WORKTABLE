"""DataProvider 抽象基类与注册表。

数据源统一实现 search()（发现/搜索，返回元信息）与
download()（获取数据，返回内存中的可加载数据），
文件落盘 / 完整性校验 / metadata 由上层 storage 统一完成，
避免"搜索 + 下载 + 导入"全部写进一个巨大函数。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from backend.services.data_providers.models import (
    ALL_KINDS,
    AuthLevel,
    DataRequest,
    DataHit,
    DataType,
    DownloadedAsset,
    ProviderCapability,
)


class DataProvider(ABC):
    """数据 Provider 抽象。

    子类必须提供 capability()，并按能力实现 search() 与/或 download()。
    所有错误都抛 errors.* 中定义的明确类型，禁止静默失败。
    """

    #: Provider 唯一 ID（小写）
    provider_id = ""
    #: 显示名
    name = ""

    @abstractmethod
    def capability(self) -> ProviderCapability:
        """返回本 Provider 的能力描述（不做网络请求）。"""

    def supports(self, kind: str) -> bool:
        cap = self.capability()
        return kind in cap.vector_kinds or kind in cap.raster_kinds

    def data_type_of(self, kind: str) -> str:
        cap = self.capability()
        if kind in cap.vector_kinds:
            return DataType.VECTOR
        if kind in cap.raster_kinds:
            return DataType.RASTER
        return ""

    # ----- 搜索（发现） -----
    def search(self, request: DataRequest) -> list:
        """搜索/发现数据，返回 DataHit 列表（元信息，不含要素）。

        数据源不支持的 kind 请抛 DataProviderError 明确说明。
        需要认证而不可用，抛 ProviderAuthError 说明如何配置。
        没有结果，抛 DataNotFoundError。
        """
        raise NotImplementedError(
            f"Provider {self.provider_id} 未实现 search()，无法搜索。"
        )

    # ----- 获取（下载到内存） -----
    def download(self, request: DataRequest) -> dict:
        """获取数据到内存。

        矢量：返回 {"geojson": FeatureCollection, "crs": "EPSG:4326", "crs_known": True}
              （CRS 为该 Provider 契约，未知必须返回 crs_known=False）。
        栅格：返回 {"raster_path": local_path, "crs": ..., ...} 或抛 Auth 错误。
        """
        raise NotImplementedError(
            f"Provider {self.provider_id} 未实现 download()，无法获取数据。"
        )


class ProviderRegistry:
    """Provider 注册表：集中管理数据源 + 能力检测 + 按类型/认证选择。"""

    def __init__(self):
        self._providers: dict[str, DataProvider] = {}
        self._installed = False

    def register(self, provider: DataProvider) -> None:
        pid = provider.provider_id
        if not pid:
            raise ValueError("DataProvider 必须定义 provider_id")
        self._providers[pid] = provider

    def _ensure_installed(self) -> None:
        """懒加载：把默认 Provider 注册进注册表（避免启动即 import 重库）。"""
        if self._installed:
            return
        self._installed = True
        # 延迟 import：这些模块顶层只引 stdlib/requests，加载廉价
        from backend.services.data_providers.osm_provider import OpenStreetMapProvider
        from backend.services.data_providers.copernicus_provider import CopernicusProvider
        from backend.services.data_providers.usgs_provider import USGSProvider
        from backend.services.data_providers.gscloud_provider import GSCloudProvider
        for cls in (OpenStreetMapProvider, CopernicusProvider, USGSProvider, GSCloudProvider):
            self.register(cls())

    def get(self, provider_id: str) -> DataProvider:
        self._ensure_installed()
        pid = str(provider_id or "").strip().lower()
        if pid not in self._providers:
            raise KeyError(pid)
        return self._providers[pid]

    def all(self) -> list:
        self._ensure_installed()
        return list(self._providers.values())

    def capabilities(self) -> list:
        """所有 Provider 能力（用于 /providers 接口与 LLM 上下文）。"""
        return [p.capability() for p in self.all()]

    def capable_providers(self, kind: str, data_type: str = "") -> list:
        """返回支持某 kind 的 Provider（按认证从公开到账号排序）。"""
        self._ensure_installed()
        out = []
        for p in self.all():
            if not p.supports(kind):
                continue
            if data_type and p.data_type_of(kind) != data_type:
                continue
            out.append(p)
        auth_rank = {"public": 0, "api_key": 1, "account": 2}
        out.sort(key=lambda p: auth_rank.get(p.capability().auth, 9))
        return out


# ============================================================
# 单例
# ============================================================
_registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    return _registry


def list_capabilities() -> list:
    """返回注册表内所有 Provider 的能力 dict 列表（供前端/接口展示）。"""
    return [c.to_dict() for c in _registry.capabilities()]


def provider_by_id(provider_id: str) -> Optional[DataProvider]:
    try:
        return _registry.get(provider_id)
    except KeyError:
        return None


def guide_hit(*, provider_id: str, provider_name: str, kind: str, area: str,
              note: str, auth: str = AuthLevel.ACCOUNT, data_type: str = DataType.RASTER,
              file_format: str = "", source_url: str = "", crs: str = "",
              title: str = "") -> DataHit:
    """构造一条"指引"结果：该 Provider 对某 kind 不可自动获取，
    但给出明确说明（downloadable=False），避免静默失败/误判无数据。"""
    return DataHit(
        title=title or f"{area or ''} - {ALL_KINDS.get(kind, kind)}（{provider_name}）",
        provider=provider_name,
        provider_id=provider_id,
        kind=kind,
        kind_label=ALL_KINDS.get(kind, kind),
        data_type=data_type,
        area=area,
        file_format=file_format,
        crs=crs,
        auth=auth,
        downloadable=False,
        source_url=source_url,
        note=note,
    )
