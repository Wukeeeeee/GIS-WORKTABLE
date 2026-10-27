"""Shared redirect checks for user-supplied HTTP(S) data sources."""

import ipaddress
import http.client
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

import requests
from requests.adapters import HTTPAdapter
from requests.utils import select_proxy
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.poolmanager import PoolManager, ProxyManager, pool_classes_by_scheme
from urllib3.util.connection import create_connection


_SENSITIVE_QUERY_KEY = re.compile(
    r"(?i)(?<![a-z0-9])(api[_-]?key|token|key|password|secret|auth|credential|signature)=([^&\s\"'<>]+)"
)
_SENSITIVE_QUERY_NAME = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:api[_-]?key|token|key|password|secret|auth|credential|signature)(?:$|[^a-z0-9])"
)
_URL_WITH_USERINFO = re.compile(r"(?i)(https?://)[^/@\s\"'<>]+@")
_EMBEDDED_HTTP_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def sanitize_http_url(url):
    """Remove credentials, sensitive query values, and fragments from a URL."""
    try:
        raw_url = str(url or "")
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return raw_url
        query = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if not _SENSITIVE_QUERY_NAME.search(key)
        ]
        netloc = parsed.netloc
        if parsed.username is not None or parsed.password is not None:
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            try:
                port = parsed.port
            except ValueError:
                port = None
            netloc = f"{host}:{port}" if port is not None else host
        return urllib.parse.urlunsplit(
            (parsed.scheme, netloc, parsed.path, urllib.parse.urlencode(query), "")
        )
    except (TypeError, ValueError):
        return "[URL 已隐藏]"


def sanitize_error_text(error, source_url=None):
    """Redact access-bearing URLs and common secret query parameters in errors."""
    detail = str(error)
    if source_url:
        raw_url = str(source_url)
        if raw_url:
            detail = detail.replace(raw_url, sanitize_http_url(raw_url))

    def sanitize_embedded(match):
        raw_url = match.group(0)
        trailing = ""
        while raw_url and raw_url[-1] in ").,;]}":
            trailing = raw_url[-1] + trailing
            raw_url = raw_url[:-1]
        return sanitize_http_url(raw_url) + trailing

    detail = _EMBEDDED_HTTP_URL.sub(sanitize_embedded, detail)
    detail = _SENSITIVE_QUERY_KEY.sub(r"\1=[已隐藏]", detail)
    detail = _URL_WITH_USERINFO.sub(r"\1[已隐藏]@", detail)
    return detail


def resolve_http_target(target_url):
    """Resolve an HTTP(S) URL once and return its public/private/unknown class plus records."""
    try:
        parsed = urllib.parse.urlsplit(target_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None, ()
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except (TypeError, ValueError):
        return None, ()

    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None, ()
    addresses = []
    for item in records:
        try:
            addresses.append(ipaddress.ip_address(item[4][0].split("%", 1)[0]))
        except (IndexError, TypeError, ValueError):
            return None, ()
    if not addresses:
        return None, ()
    classifications = {address.is_global for address in addresses}
    if len(classifications) != 1:
        return None, tuple(records)
    return classifications.pop(), tuple(records)


def is_public_http_target(target_url):
    """Return True/False for globally routable HTTP(S), or None if unknown."""
    return resolve_http_target(target_url)[0]


def _http_origin_key(target_url):
    try:
        parsed = urllib.parse.urlsplit(target_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        return (
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
        )
    except (TypeError, ValueError):
        return None


def redirect_origin_key(target_url):
    try:
        parsed = urllib.parse.urlsplit(target_url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        scheme = parsed.scheme.lower()
        return (scheme, parsed.hostname.lower(), parsed.port or (443 if scheme == "https" else 80))
    except (TypeError, ValueError):
        return None


def strip_query_parameters(target_url, parameter_names):
    if not parameter_names:
        return target_url
    try:
        parsed = urllib.parse.urlsplit(target_url)
        blocked_names = {str(name).casefold() for name in parameter_names}
        query = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in blocked_names
        ]
        return urllib.parse.urlunsplit((
            parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment,
        ))
    except (TypeError, ValueError):
        return target_url


def sensitive_query_parameter_names(target_url):
    try:
        parsed = urllib.parse.urlsplit(target_url)
        return {
            key for key, _value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            if _SENSITIVE_QUERY_NAME.search(key)
        }
    except (TypeError, ValueError):
        return set()


def _query_has_credential(target_url, parameter_names):
    if not parameter_names:
        return False
    try:
        parsed = urllib.parse.urlsplit(target_url)
        names = {str(name).casefold() for name in parameter_names if name}
        return any(
            key.casefold() in names and bool(value)
            for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        )
    except (TypeError, ValueError):
        return False


def _public_http_credential_is_insecure(target_url, classification, connection_policy):
    try:
        is_http = urllib.parse.urlsplit(target_url).scheme.lower() == "http"
    except (TypeError, ValueError):
        return False
    return (
        is_http
        and classification is not False
        and _query_has_credential(
            target_url, connection_policy.get("https_credential_parameters")
        )
    )


def _public_http_userinfo_is_insecure(target_url, classification):
    try:
        parsed = urllib.parse.urlsplit(target_url)
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme.lower() == "http"
        and classification is not False
        and (parsed.username is not None or parsed.password is not None)
    )


def redirect_is_allowed(target_url, protect_public_target):
    try:
        target = urllib.parse.urlsplit(target_url)
        valid_target = (
            target.scheme.lower() in {"http", "https"}
            and bool(target.hostname)
            and not target.username
            and not target.password
        )
    except (TypeError, ValueError):
        return False
    return valid_target and (
        not protect_public_target or is_public_http_target(target_url) is True
    )


def _host_header(parsed):
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if parsed.port and parsed.port != default_port:
        host = f"{host}:{parsed.port}"
    return host


def _url_with_pinned_address(target_url, records):
    parsed = urllib.parse.urlsplit(target_url)
    host = records[0][4][0]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


class SafeHTTPRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(
        self, protect_public_target, connection_policy=None, credential_parameters=None,
        reject_authenticated_cross_origin=False,
    ):
        super().__init__()
        self.protect_public_target = protect_public_target
        self.connection_policy = connection_policy
        self.credential_parameters = {
            str(name).casefold() for name in (credential_parameters or ()) if name
        }
        self.reject_authenticated_cross_origin = bool(reject_authenticated_cross_origin)
        self.credentials_stripped = False
        self.authenticated_redirect_blocked = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        is_cross_origin = redirect_origin_key(req.full_url) != redirect_origin_key(newurl)
        if (
            self.reject_authenticated_cross_origin
            and is_cross_origin
            and _query_has_credential(req.full_url, self.credential_parameters)
        ):
            self.authenticated_redirect_blocked = True
            raise urllib.error.HTTPError(
                req.full_url, 403, "Authenticated cross-origin redirect is not allowed", headers, fp
            )
        if not redirect_is_allowed(newurl, self.protect_public_target):
            raise urllib.error.HTTPError(
                req.full_url, 403, "Redirect target is not allowed", headers, fp
            )
        # A user-selected private origin may redirect to a public CDN. Once the
        # chain reaches a public or ambiguously classified host, keep the guard
        # active so later redirects cannot pivot back into the local network.
        if is_public_http_target(newurl) is not False:
            self.protect_public_target = True
        if self.protect_public_target and self.connection_policy is not None:
            self.connection_policy["require_public_target"] = True
        if (
            self.credential_parameters
            and is_cross_origin
        ):
            stripped_url = strip_query_parameters(newurl, self.credential_parameters)
            self.credentials_stripped = self.credentials_stripped or stripped_url != newurl
            newurl = stripped_url
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PinnedAddressStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._records = {}

    def set(self, host, port, records):
        with self._lock:
            self._records[(host.lower(), port)] = records

    def get(self, host, port):
        with self._lock:
            return self._records.get((host.lower(), port), ())


def _connect_pinned_socket(connection, pin_store):
    records = pin_store.get(connection.host, connection.port) if pin_store else ()
    last_error = None
    for record in records:
        try:
            return socket.create_connection(
                record[4], timeout=connection.timeout,
                source_address=connection.source_address,
            )
        except OSError as exc:
            last_error = exc
    raise OSError(f"No checked address could be reached for {connection.host}: {last_error or 'no addresses'}")


class _PinnedUrllibHTTPConnection(http.client.HTTPConnection):
    _default_pin_store = None

    def connect(self):
        if self._tunnel_host:
            raise OSError("Pinned direct connection cannot use a proxy tunnel")
        self.sock = _connect_pinned_socket(self, self._default_pin_store)


class _PinnedUrllibHTTPSConnection(http.client.HTTPSConnection):
    _default_pin_store = None

    def connect(self):
        if self._tunnel_host:
            raise OSError("Pinned direct connection cannot use a proxy tunnel")
        raw_sock = _connect_pinned_socket(self, self._default_pin_store)
        try:
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            raw_sock.close()
            raise


class _PinnedUrllibProxyHTTPSConnection(http.client.HTTPSConnection):
    _default_pin_store = None

    def set_tunnel(self, host, port=None, headers=None):
        records = self._default_pin_store.get(host, port or 443) if self._default_pin_store else ()
        if not records:
            raise OSError("No checked address is available for the HTTPS proxy tunnel")
        self._origin_tls_hostname = host
        address = records[0][4][0]
        super().set_tunnel(address, port=port, headers=headers)

    def connect(self):
        if not self._tunnel_host:
            return super().connect()
        raw_sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout, source_address=self.source_address,
        )
        try:
            self.sock = raw_sock
            self._tunnel()
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self._origin_tls_hostname)
        except Exception:
            raw_sock.close()
            raise


def _request_uses_proxy(req):
    try:
        target = urllib.parse.urlsplit(req.full_url)
        connection = urllib.parse.urlsplit("//" + req.host)
        return (
            (target.hostname or "").lower(), target.port
        ) != (
            (connection.hostname or "").lower(), connection.port
        )
    except (TypeError, ValueError):
        return True


class _SafePinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, connection_policy, pin_store, debuglevel=0):
        super().__init__(debuglevel=debuglevel)
        self.connection_policy = connection_policy
        self.pin_store = pin_store
        self._connection_class = type(
            "PinnedUrllibHTTPConnection", (_PinnedUrllibHTTPConnection,),
            {"_default_pin_store": pin_store},
        )

    def http_open(self, req):
        origin_key = _http_origin_key(req.full_url)
        if _request_uses_proxy(req):
            classification, records = resolve_http_target(req.full_url)
            if (
                not records
                or (self.connection_policy.get("initial_private_origin") == origin_key and classification is not False)
                or (self.connection_policy["require_public_target"] and classification is not True)
                or _public_http_credential_is_insecure(req.full_url, classification, self.connection_policy)
                or _public_http_userinfo_is_insecure(req.full_url, classification)
            ):
                raise urllib.error.URLError("Target failed the public DNS safety check")
            parsed = urllib.parse.urlsplit(req.full_url)
            port = parsed.port or 80
            self.pin_store.set(parsed.hostname, port, records)
            original_selector = req.selector
            original_headers = dict(req.headers)
            original_unredirected_headers = dict(req.unredirected_hdrs)
            req.selector = _url_with_pinned_address(req.full_url, records)
            req.headers["Host"] = _host_header(parsed)
            try:
                return self.do_open(http.client.HTTPConnection, req)
            finally:
                req.selector = original_selector
                req.headers.clear()
                req.headers.update(original_headers)
                req.unredirected_hdrs.clear()
                req.unredirected_hdrs.update(original_unredirected_headers)
        classification, records = resolve_http_target(req.full_url)
        if (
            not records
            or (self.connection_policy.get("initial_private_origin") == origin_key and classification is not False)
            or (self.connection_policy["require_public_target"] and classification is not True)
            or _public_http_credential_is_insecure(req.full_url, classification, self.connection_policy)
            or _public_http_userinfo_is_insecure(req.full_url, classification)
        ):
            raise urllib.error.URLError("Target failed the public DNS safety check")
        parsed = urllib.parse.urlsplit(req.full_url)
        port = parsed.port or 80
        self.pin_store.set(parsed.hostname, port, records)
        return self.do_open(self._connection_class, req)


class _SafePinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, connection_policy, pin_store, debuglevel=None, context=None, check_hostname=None):
        super().__init__(debuglevel=debuglevel, context=context, check_hostname=check_hostname)
        self.connection_policy = connection_policy
        self.pin_store = pin_store
        self._connection_class = type(
            "PinnedUrllibHTTPSConnection", (_PinnedUrllibHTTPSConnection,),
            {"_default_pin_store": pin_store},
        )

    def https_open(self, req):
        origin_key = _http_origin_key(req.full_url)
        if _request_uses_proxy(req):
            classification, records = resolve_http_target(req.full_url)
            if (
                not records
                or (self.connection_policy.get("initial_private_origin") == origin_key and classification is not False)
                or (self.connection_policy["require_public_target"] and classification is not True)
            ):
                raise urllib.error.URLError("Target failed the public DNS safety check")
            parsed = urllib.parse.urlsplit(req.full_url)
            port = parsed.port or 443
            self.pin_store.set(parsed.hostname, port, records)
            proxy_connection_class = type(
                "PinnedUrllibProxyHTTPSConnection", (_PinnedUrllibProxyHTTPSConnection,),
                {"_default_pin_store": self.pin_store},
            )
            return self.do_open(proxy_connection_class, req, context=self._context)
        classification, records = resolve_http_target(req.full_url)
        if (
            not records
            or (self.connection_policy.get("initial_private_origin") == origin_key and classification is not False)
            or (self.connection_policy["require_public_target"] and classification is not True)
        ):
            raise urllib.error.URLError("Target failed the public DNS safety check")
        parsed = urllib.parse.urlsplit(req.full_url)
        port = parsed.port or 443
        self.pin_store.set(parsed.hostname, port, records)
        return self.do_open(self._connection_class, req, context=self._context)


class _PinnedConnectionMixin:
    _default_pin_store = None

    def __init__(self, *args, pin_store=None, **kwargs):
        self._pin_store = pin_store or self._default_pin_store
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        records = self._pin_store.get(self._dns_host, self.port) if self._pin_store else ()
        last_error = None
        for family, _socktype, _proto, _canonname, sockaddr in records:
            try:
                return create_connection(
                    (sockaddr[0], self.port),
                    self.timeout,
                    source_address=self.source_address,
                    socket_options=self.socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise NewConnectionError(
            self,
            f"No pinned address could be reached for {self.host}: {last_error or 'no addresses'}",
        )


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedPoolManager(PoolManager):
    def __init__(self, *args, pin_store, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = dict(pool_classes_by_scheme)
        pinned_http_connection = type(
            "PinnedHTTPConnectionForPool", (_PinnedHTTPConnection,),
            {"_default_pin_store": pin_store},
        )
        pinned_https_connection = type(
            "PinnedHTTPSConnectionForPool", (_PinnedHTTPSConnection,),
            {"_default_pin_store": pin_store},
        )
        pinned_http_pool = type(
            "PinnedHTTPConnectionPoolForManager", (_PinnedHTTPConnectionPool,),
            {"ConnectionCls": pinned_http_connection},
        )
        pinned_https_pool = type(
            "PinnedHTTPSConnectionPoolForManager", (_PinnedHTTPSConnectionPool,),
            {"ConnectionCls": pinned_https_connection},
        )
        self.pool_classes_by_scheme.update({
            "http": pinned_http_pool,
            "https": pinned_https_pool,
        })


class _PinnedProxyHTTPSConnection(HTTPSConnection):
    _default_pin_store = None

    def set_tunnel(self, host, port=None, headers=None, scheme="http"):
        records = self._default_pin_store.get(host, port or 443) if self._default_pin_store else ()
        if not records:
            raise OSError("No checked address is available for the HTTPS proxy tunnel")
        address = records[0][4][0]
        self.server_hostname = host
        self.assert_hostname = host
        super().set_tunnel(address, port=port, headers=headers, scheme=scheme)


class _PinnedProxyManager(ProxyManager):
    def __init__(self, *args, pin_store, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = dict(pool_classes_by_scheme)
        pinned_connection = type(
            "PinnedProxyHTTPSConnectionForManager", (_PinnedProxyHTTPSConnection,),
            {"_default_pin_store": pin_store},
        )
        pinned_pool = type(
            "PinnedProxyHTTPSConnectionPoolForManager", (HTTPSConnectionPool,),
            {"ConnectionCls": pinned_connection},
        )
        self.pool_classes_by_scheme["https"] = pinned_pool


class PinnedAddressHTTPAdapter(HTTPAdapter):
    """For direct Requests traffic, connect to the exact DNS answers just checked."""

    def __init__(self, require_public_target, initial_private_url=None):
        self.require_public_target = require_public_target
        self.initial_private_origin = _http_origin_key(initial_private_url)
        self.pin_store = _PinnedAddressStore()
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self._pool_connections = connections
        self._pool_maxsize = maxsize
        self._pool_block = block
        self.poolmanager = _PinnedPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            pin_store=self.pin_store,
            **pool_kwargs,
        )

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        if proxy in self.proxy_manager:
            return self.proxy_manager[proxy]
        if proxy.lower().startswith("socks"):
            return super().proxy_manager_for(proxy, **proxy_kwargs)
        manager = _PinnedProxyManager(
            proxy,
            num_pools=self._pool_connections,
            maxsize=self._pool_maxsize,
            block=self._pool_block,
            proxy_headers=self.proxy_headers(proxy),
            pin_store=self.pin_store,
            **proxy_kwargs,
        )
        self.proxy_manager[proxy] = manager
        return manager

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        proxy = select_proxy(request.url, proxies or {})
        if proxy and proxy.lower().startswith("socks") and self.require_public_target:
            raise requests.ConnectionError("当前 SOCKS 代理无法固定远端 DNS 地址，已阻止该请求")
        classification, records = resolve_http_target(request.url)
        if (
            not records
            or (_http_origin_key(request.url) == self.initial_private_origin and classification is not False)
            or (self.require_public_target and classification is not True)
        ):
            raise requests.ConnectionError("目标地址在连接时未通过公网 DNS 安全检查")
        if (
            _public_http_credential_is_insecure(
                request.url, classification,
                {"https_credential_parameters": sensitive_query_parameter_names(request.url)},
            )
            or _public_http_userinfo_is_insecure(request.url, classification)
        ):
            raise requests.ConnectionError("公网 HTTP 不允许明文发送凭据，请改用 HTTPS")
        parsed = urllib.parse.urlsplit(request.url)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        self.pin_store.set(parsed.hostname, port, records)
        original_url = request.url
        original_host = request.headers.get("Host")
        rewrite_for_http_proxy = bool(proxy) and parsed.scheme.lower() == "http"
        if rewrite_for_http_proxy:
            request.url = _url_with_pinned_address(original_url, records)
            request.headers["Host"] = original_host or _host_header(parsed)
        try:
            response = super().send(request, stream, timeout, verify, cert, proxies)
        finally:
            request.url = original_url
            if rewrite_for_http_proxy:
                if original_host is None:
                    request.headers.pop("Host", None)
                else:
                    request.headers["Host"] = original_host
        if response is not None:
            response.url = original_url
        return response


def safe_redirect_opener(
    proxy_handler,
    initial_url,
    credential_parameters=None,
    strip_sensitive_query=True,
    require_https_for_credentials=None,
    reject_authenticated_cross_origin=False,
):
    """Create an urllib opener following the user's private-network policy."""
    initial_classification = is_public_http_target(initial_url)
    if initial_classification is not True:
        # Only clearly public origins use a proxy. Private, mixed, and unknown
        # origins stay on the locally checked direct path.
        proxy_handler = urllib.request.ProxyHandler({})
    protect_public_target = initial_classification is not False
    redirect_credential_parameters = set(credential_parameters or ())
    if strip_sensitive_query:
        redirect_credential_parameters.update(sensitive_query_parameter_names(initial_url))
    https_credential_parameters = set(require_https_for_credentials or ())
    https_credential_parameters.update(sensitive_query_parameter_names(initial_url))
    # Unknown or mixed DNS answers are not a user-selected private origin.
    # Fail closed unless the initial target resolves clearly to private space.
    connection_policy = {
        "require_public_target": initial_classification is not False,
        "initial_private_origin": _http_origin_key(initial_url) if initial_classification is False else None,
        "https_credential_parameters": {str(name).casefold() for name in https_credential_parameters if name},
    }
    pin_store = _PinnedAddressStore()
    return urllib.request.build_opener(
        proxy_handler,
        SafeHTTPRedirectHandler(
            protect_public_target, connection_policy, redirect_credential_parameters,
            reject_authenticated_cross_origin=reject_authenticated_cross_origin,
        ),
        _SafePinnedHTTPHandler(connection_policy, pin_store),
        _SafePinnedHTTPSHandler(connection_policy, pin_store),
    )
