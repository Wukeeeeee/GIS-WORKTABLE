"""Use configured proxies, ignoring only unreachable loopback system proxies."""
import socket
import ipaddress
import time
import urllib.request
from urllib.parse import urlsplit


def effective_model_proxy(url, timeout=0.3):
    from backend.services.tools import get_proxy_config
    custom = get_proxy_config()
    if custom:
        return custom
    try:
        target = urlsplit(url)
        target_host = target.hostname
    except (TypeError, ValueError):
        return None
    if not target_host:
        return None
    if urllib.request.proxy_bypass(target_host):
        return None
    proxies = urllib.request.getproxies()
    proxy = proxies.get(target.scheme) or proxies.get('all')
    if not proxy:
        return None
    try:
        parsed = urlsplit(proxy if '://' in proxy else 'http://' + proxy)
        host = parsed.hostname or ""
        port = parsed.port  # 读取属性以便拒绝越界/非数字端口，而不是把坏值交给客户端。
    except (TypeError, ValueError):
        return None
    if not host:
        return None
    try:
        is_loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.lower() == "localhost"
    if is_loopback:
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        addresses = ("127.0.0.1", "::1") if host.lower() == "localhost" else (host,)
        deadline = time.monotonic() + max(0.001, timeout)
        connected = False
        for address in addresses:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                with socket.create_connection((address, port or default_port), timeout=remaining):
                    connected = True
                    break
            except OSError:
                continue
        if not connected:
            return None
    return proxy
