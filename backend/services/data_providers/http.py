"""统一 HTTP 请求：超时、重试次数限制、响应大小限制。

所有 Provider 的网络请求都必须经过本模块，以便：
  1. 统一超时处理（不无限等待）；
  2. 下载失败可重试，但重试次数受限（默认 2 次，最多 4 次）；
  3. 对响应体大小设上限（防止把"整个互联网"当数据源拉爆内存）；
  4. 测试时只需 patch request_once 一个入口即可完整模拟网络。

错误全部抛 errors 里的明确类型，禁止静默失败。
"""

from __future__ import annotations

import time
from typing import Optional

from backend.services.data_providers.errors import (
    DownloadTimeoutError,
    DataValidationError,
    ProviderUnavailableError,
)

_USER_AGENT = "GIS-WorkTable-DataProvider/1.0 (GIS desktop; data discovery)"
# 单次响应上限：默认 512MB（真实遥感大文件也走分块流式，超限即中断）
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0            # 秒（连接 + 读）
DEFAULT_RETRIES = 2               # 重试次数（不算首次），避免无限重试
MAX_RETRIES = 4
_CHUNK = 64 * 1024


def request_once(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    stream: bool = True,
) -> bytes:
    """发送单次 HTTP 请求，返回响应字节。

    网络层错误统一转为明确异常：
      - 超时        -> DownloadTimeoutError
      - HTTP 错误   -> ProviderUnavailableError
      - 内容超限    -> DataValidationError
      - 其它连接错误-> ProviderUnavailableError
    """
    import requests

    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)

    try:
        resp = requests.request(
            method, url,
            params=params, data=data, json=json_body, headers=hdrs,
            timeout=timeout, stream=stream,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout as e:
        raise DownloadTimeoutError(
            f"请求超时：{url}（{timeout} 秒无响应）",
            hint="数据源响应过慢，可稍后重试，或缩小空间范围。",
        ) from e
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, "status_code", None)
        raise ProviderUnavailableError(
            f"数据源 HTTP 错误：{url} → HTTP {code}",
            hint="该数据源服务异常或拒绝了该请求。",
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise ProviderUnavailableError(
            f"数据源连接失败：{url}（无法建立连接）",
            hint="请检查网络，或更换数据源镜像。",
        ) from e
    except requests.exceptions.RequestException as e:
        raise ProviderUnavailableError(f"数据源请求失败：{url}：{e}") from e

    # 分块读取并限制大小（流式，避免一次性读入超大数据）
    chunks = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            total += len(chunk)
            if total > max_bytes:
                raise DataValidationError(
                    f"数据响应超过大小上限（{max_bytes // (1024 * 1024)} MB），已中断。",
                    hint="数据过大，请缩小空间范围或按区域分块获取。",
                )
            chunks.append(chunk)
    except DataValidationError:
        resp.close()
        raise
    finally:
        if not stream:
            resp.close()
    return b"".join(chunks)


def request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff: float = 0.5,
    **kwargs,
) -> bytes:
    """带重试的请求。retries 受限（<= MAX_RETRIES），指数退避。

    对 ProviderUnavailableError / DownloadTimeoutError 重试；
    对 DataValidationError（内容超限等数据本身问题）不重试，直接抛。
    """
    retries = max(0, min(int(retries), MAX_RETRIES))
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return request_once(method, url, **kwargs)
        except (ProviderUnavailableError, DownloadTimeoutError) as e:
            last_err = e
            if attempt >= retries:
                break
            # 退避等待，避免把数据源打死
            time.sleep(backoff * (2 ** attempt))
    # 重试用尽后，若原始错误是超时，归一到 DownloadTimeoutError
    if isinstance(last_err, DownloadTimeoutError):
        raise DownloadTimeoutError(
            f"请求持续超时：{url}（已重试 {retries} 次）。",
            hint="网络到数据源不稳定，请稍后重试或改用其它数据源。",
        ) from last_err
    raise ProviderUnavailableError(
        f"数据源不可用：{url}（已重试 {retries} 次）。",
        hint="多次请求仍失败，请检查网络后重试。",
    ) from last_err


# ============================================================
# 便捷封装
# ============================================================

def get_bytes(url: str, *, timeout: float = DEFAULT_TIMEOUT,
              max_bytes: int = DEFAULT_MAX_BYTES, params: Optional[dict] = None,
              headers: Optional[dict] = None, retries: int = DEFAULT_RETRIES) -> bytes:
    return request_with_retry(
        "GET", url, params=params, headers=headers,
        timeout=timeout, max_bytes=max_bytes, retries=retries,
    )


def post_bytes(url: str, *, data: Optional[dict] = None,
               timeout: float = DEFAULT_TIMEOUT,
               max_bytes: int = DEFAULT_MAX_BYTES,
               headers: Optional[dict] = None, retries: int = DEFAULT_RETRIES) -> bytes:
    return request_with_retry(
        "POST", url, data=data, headers=headers,
        timeout=timeout, max_bytes=max_bytes, retries=retries,
    )


def post_json(url: str, *, json_body: Optional[dict] = None,
              timeout: float = DEFAULT_TIMEOUT,
              max_bytes: int = DEFAULT_MAX_BYTES,
              headers: Optional[dict] = None, retries: int = DEFAULT_RETRIES) -> dict:
    """POST JSON body 并解析 JSON 响应。"""
    import json
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    raw = request_with_retry(
        "POST", url, json_body=json_body, headers=hdrs,
        timeout=timeout, max_bytes=max_bytes, retries=retries,
    )
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DataValidationError(
            f"数据源返回内容无法解析为 JSON：{url}",
            hint="接口返回格式异常，已拒绝使用。",
        ) from e


def get_json(url: str, **kwargs) -> list | dict:
    """GET 并解析 JSON；解析失败视为数据格式错误。"""
    import json
    raw = get_bytes(url, **kwargs)
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DataValidationError(
            f"数据源返回内容无法解析为 JSON：{url}",
            hint="接口返回格式异常，属数据源侧问题，已拒绝使用。",
        ) from e


def post_overpass(query: str, url: str, *,
                  timeout: float = 90.0,
                  max_bytes: int = DEFAULT_MAX_BYTES,
                  retries: int = DEFAULT_RETRIES) -> dict:
    """向 Overpass API POST 查询并解析 JSON。"""
    import json
    raw = post_bytes(
        url,
        data={"data": query},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout, max_bytes=max_bytes, retries=retries,
    )
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DataValidationError(
            f"Overpass 返回内容无法解析（{url[:60]}…），数据格式错误。",
            hint="该 Overpass 镜像返回异常，已拒绝使用该响应。",
        ) from e
