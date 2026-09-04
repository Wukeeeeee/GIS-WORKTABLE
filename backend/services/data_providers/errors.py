"""数据 Provider 的错误类型。

约定：所有错误都要给出对用户/LLM 可读的中文 message，
禁止静默失败；被外层工具捕获后转为文字回复。
"""


class DataProviderError(Exception):
    """所有数据 Provider 错误的基类。"""

    def __init__(self, message: str, *, provider: str = "", hint: str = ""):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.hint = hint

    def to_dict(self) -> dict:
        d = {"error": self.message, "type": type(self).__name__}
        if self.provider:
            d["provider"] = self.provider
        if self.hint:
            d["hint"] = self.hint
        return d


class ProviderAuthError(DataProviderError):
    """需要认证 / 授权（账号登录、API Key），当前未配置或未通过。"""


class DataNotFoundError(DataProviderError):
    """搜索无结果，或指定区域/要素类型在数据源中不存在。"""


class DownloadError(DataProviderError):
    """下载/获取失败（网络、服务端、数据读取等）。"""


class DownloadTimeoutError(DownloadError):
    """网络超时（重试次数用尽后仍超时）。"""


class DataValidationError(DataProviderError):
    """数据本身不合法：格式错误、CRS 缺失/未知、超出大小限制、要素为空等。

    这类错误意味着该数据不应被写入或加载到地图。
    """


class ProviderUnavailableError(DataProviderError):
    """数据源暂时不可用（HTTP 错误、连接失败、服务端异常）。"""
