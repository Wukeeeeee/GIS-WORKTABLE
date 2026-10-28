"""Shared redirect checks for user-supplied HTTP(S) data sources."""

import ipaddress
import concurrent.futures
import http.client
import re
import socket
import threading
import time
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

# DNS lookups are blocking and cannot be interrupted once libc has started one.
# Keep timed lookups on a small pool and cap outstanding work, since a stuck
# libc resolver call cannot be interrupted after the caller's deadline expires.
_DNS_LOOKUP_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="url-security-dns"
)
_DNS_LOOKUP_SLOTS = threading.BoundedSemaphore(4)


def _request_dns_timeout(timeout):
    """Bound DNS checks by Requests' connect timeout, with a finite default."""
    if hasattr(timeout, "connect_timeout"):
        timeout = timeout.connect_timeout
    if isinstance(timeout, (tuple, list)):
        timeout = timeout[0] if timeout else None
    try:
        return max(0.0, float(timeout)) if timeout is not None else 10.0
    except (TypeError, ValueError):
        return 10.0


def _timed_getaddrinfo(host, port, timeout):
    if not _DNS_LOOKUP_SLOTS.acquire(blocking=False):
        raise concurrent.futures.TimeoutError()
    try:
        future = _DNS_LOOKUP_EXECUTOR.submit(
            socket.getaddrinfo, host, port, type=socket.SOCK_STREAM
        )
    except BaseException:
        _DNS_LOOKUP_SLOTS.release()
        raise
    future.add_done_callback(lambda _future: _DNS_LOOKUP_SLOTS.release())
    return future.result(timeout=max(0.0, timeout))


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


def resolve_http_target(target_url, timeout=None):
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
        if timeout is None:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        else:
            remaining = max(0.0, float(timeout))
            records = _timed_getaddrinfo(host, port, remaining)
    except concurrent.futures.TimeoutError:
        return None, ()
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


def is_public_http_target(target_url, timeout=None):
    """Return True/False for globally routable HTTP(S), or None if unknown."""
    return resolve_http_target(target_url, timeout=timeout)[0]


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


def _resolve_http_target_before(target_url, deadline):
    if deadline is None:
        return resolve_http_target(target_url)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None, ()
    return resolve_http_target(target_url, timeout=remaining)


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


_CLASSIFICATION_UNSET = object()


def redirect_is_allowed(
    target_url, protect_public_target, target_classification=_CLASSIFICATION_UNSET,
):
    try:
        target = urllib.parse.urlsplit(target_url)
        valid_target = (
            target.scheme.lower() in {"http", "https"}
            and bool(target.hostname)
            and target.username is None
            and target.password is None
        )
    except (TypeError, ValueError):
        return False
    if not valid_target or not protect_public_target:
        return valid_target
    if target_classification is _CLASSIFICATION_UNSET:
        target_classification = is_public_http_target(target_url)
    return target_classification is True


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
        reject_authenticated_cross_origin=False, header_deadline=None,
    ):
        super().__init__()
        self.protect_public_target = protect_public_target
        self.connection_policy = connection_policy
        self.credential_parameters = {
            str(name).casefold() for name in (credential_parameters or ()) if name
        }
        self.reject_authenticated_cross_origin = bool(reject_authenticated_cross_origin)
        self.header_deadline = header_deadline
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
        classification, _records = _resolve_http_target_before(newurl, self.header_deadline)
        if self.header_deadline is not None and time.monotonic() >= self.header_deadline:
            raise TimeoutError("HTTP redirect DNS deadline exceeded")
        if not redirect_is_allowed(
            newurl, self.protect_public_target, target_classification=classification,
        ):
            raise urllib.error.HTTPError(
                req.full_url, 403, "Redirect target is not allowed", headers, fp
            )
        # A user-selected private origin may redirect to a public CDN. Once the
        # chain reaches a public or ambiguously classified host, keep the guard
        # active so later redirects cannot pivot back into the local network.
        if classification is not False:
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


def _connect_pinned_socket(connection, pin_store, deadline=None):
    records = pin_store.get(connection.host, connection.port) if pin_store else ()
    last_error = None
    for record in records:
        try:
            timeout = connection.timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("HTTP connection deadline exceeded")
                timeout = remaining if timeout is None else min(timeout, remaining)
            return socket.create_connection(
                record[4], timeout=timeout,
                source_address=connection.source_address,
            )
        except OSError as exc:
            last_error = exc
            if deadline is not None and deadline <= time.monotonic():
                raise TimeoutError("HTTP connection deadline exceeded") from exc
    raise OSError(f"No checked address could be reached for {connection.host}: {last_error or 'no addresses'}")


class _PinnedUrllibHTTPConnection(http.client.HTTPConnection):
    _default_pin_store = None
    _connect_deadline = None

    def connect(self):
        if self._tunnel_host:
            raise OSError("Pinned direct connection cannot use a proxy tunnel")
        self.sock = _connect_pinned_socket(self, self._default_pin_store, self._connect_deadline)


class _PinnedUrllibHTTPSConnection(http.client.HTTPSConnection):
    _default_pin_store = None
    _connect_deadline = None

    def connect(self):
        if self._tunnel_host:
            raise OSError("Pinned direct connection cannot use a proxy tunnel")
        raw_sock = _connect_pinned_socket(self, self._default_pin_store, self._connect_deadline)
        try:
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            raw_sock.close()
            raise


class _PinnedUrllibProxyHTTPSConnection(http.client.HTTPSConnection):
    _default_pin_store = None
    _connect_deadline = None

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
        timeout = self.timeout
        if self._connect_deadline is not None:
            remaining = self._connect_deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP connection deadline exceeded")
            timeout = remaining if timeout is None else min(timeout, remaining)
        raw_sock = socket.create_connection((self.host, self.port), timeout=timeout,
                                            source_address=self.source_address)
        try:
            self.sock = raw_sock
            self._tunnel()
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self._origin_tls_hostname)
        except Exception:
            raw_sock.close()
            raise


class _DeadlineHeaderReader:
    """Read HTTP header lines with a monotonic deadline checked per byte."""

    def __init__(self, stream, sock, deadline):
        self._stream = stream
        self._sock = sock
        self._deadline = deadline

    def readline(self, limit=-1):
        result = bytearray()
        while limit < 0 or len(result) < limit:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP response header deadline exceeded")
            self._sock.settimeout(remaining)
            char = self._stream.read(1)
            if not char:
                break
            result.extend(char)
            if char == b"\n":
                break
        return bytes(result)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _DeadlineHTTPResponse(http.client.HTTPResponse):
    _header_deadline = None

    def __init__(self, sock, *args, **kwargs):
        super().__init__(sock, *args, **kwargs)
        if self._header_deadline is not None:
            self.fp = _DeadlineHeaderReader(self.fp, sock, self._header_deadline)


def _connection_class_with_header_deadline(connection_class, deadline):
    response_class = type(
        "DeadlineHTTPResponse", (_DeadlineHTTPResponse,), {"_header_deadline": deadline},
    )
    return type(
        "DeadlineHTTPConnection", (connection_class,),
        {"response_class": response_class, "_connect_deadline": deadline},
    )


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
    def __init__(self, connection_policy, pin_store, debuglevel=0, header_deadline=None):
        super().__init__(debuglevel=debuglevel)
        self.connection_policy = connection_policy
        self.pin_store = pin_store
        self.header_deadline = header_deadline
        connection_base = _PinnedUrllibHTTPConnection
        if header_deadline is not None:
            connection_base = _connection_class_with_header_deadline(connection_base, header_deadline)
        self._connection_class = type(
            "PinnedUrllibHTTPConnection", (connection_base,),
            {"_default_pin_store": pin_store},
        )

    def http_open(self, req):
        origin_key = _http_origin_key(req.full_url)
        if _request_uses_proxy(req):
            classification, records = _resolve_http_target_before(req.full_url, self.header_deadline)
            if (
                self.connection_policy.get("initial_private_origin") == origin_key
                and classification is not False
            ):
                raise urllib.error.URLError("Target failed the public DNS safety check")
            if _public_http_credential_is_insecure(req.full_url, classification, self.connection_policy):
                raise urllib.error.URLError("GeoSource credentials over public HTTP require HTTPS")
            if (
                not records
                or (self.connection_policy["require_public_target"] and classification is not True)
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
                connection_class = http.client.HTTPConnection
                if self.header_deadline is not None:
                    connection_class = _connection_class_with_header_deadline(connection_class, self.header_deadline)
                return self.do_open(connection_class, req)
            finally:
                req.selector = original_selector
                req.headers.clear()
                req.headers.update(original_headers)
                req.unredirected_hdrs.clear()
                req.unredirected_hdrs.update(original_unredirected_headers)
        classification, records = _resolve_http_target_before(req.full_url, self.header_deadline)
        if (
            self.connection_policy.get("initial_private_origin") == origin_key
            and classification is not False
        ):
            raise urllib.error.URLError("Target failed the public DNS safety check")
        if _public_http_credential_is_insecure(req.full_url, classification, self.connection_policy):
            raise urllib.error.URLError("GeoSource credentials over public HTTP require HTTPS")
        if (
            not records
            or (self.connection_policy["require_public_target"] and classification is not True)
            or _public_http_userinfo_is_insecure(req.full_url, classification)
        ):
            raise urllib.error.URLError("Target failed the public DNS safety check")
        parsed = urllib.parse.urlsplit(req.full_url)
        port = parsed.port or 80
        self.pin_store.set(parsed.hostname, port, records)
        return self.do_open(self._connection_class, req)


class _SafePinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, connection_policy, pin_store, debuglevel=None, context=None, check_hostname=None,
                 header_deadline=None):
        super().__init__(debuglevel=debuglevel, context=context, check_hostname=check_hostname)
        self.connection_policy = connection_policy
        self.pin_store = pin_store
        self.header_deadline = header_deadline
        connection_base = _PinnedUrllibHTTPSConnection
        if header_deadline is not None:
            connection_base = _connection_class_with_header_deadline(connection_base, header_deadline)
        self._connection_class = type(
            "PinnedUrllibHTTPSConnection", (connection_base,),
            {"_default_pin_store": pin_store},
        )

    def https_open(self, req):
        origin_key = _http_origin_key(req.full_url)
        if _request_uses_proxy(req):
            classification, records = _resolve_http_target_before(req.full_url, self.header_deadline)
            if (
                not records
                or (self.connection_policy.get("initial_private_origin") == origin_key and classification is not False)
                or (self.connection_policy["require_public_target"] and classification is not True)
            ):
                raise urllib.error.URLError("Target failed the public DNS safety check")
            parsed = urllib.parse.urlsplit(req.full_url)
            port = parsed.port or 443
            self.pin_store.set(parsed.hostname, port, records)
            proxy_base = _PinnedUrllibProxyHTTPSConnection
            if self.header_deadline is not None:
                proxy_base = _connection_class_with_header_deadline(proxy_base, self.header_deadline)
            proxy_connection_class = type(
                "PinnedUrllibProxyHTTPSConnection", (proxy_base,),
                {"_default_pin_store": self.pin_store},
            )
            return self.do_open(proxy_connection_class, req, context=self._context)
        classification, records = _resolve_http_target_before(req.full_url, self.header_deadline)
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
        classification, records = resolve_http_target(
            request.url, timeout=_request_dns_timeout(timeout),
        )
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
    header_deadline=None,
):
    """Create an urllib opener following the user's private-network policy."""
    initial_classification = _resolve_http_target_before(initial_url, header_deadline)[0]
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
            header_deadline=header_deadline,
        ),
        _SafePinnedHTTPHandler(connection_policy, pin_store, header_deadline=header_deadline),
        _SafePinnedHTTPSHandler(connection_policy, pin_store, header_deadline=header_deadline),
    )
