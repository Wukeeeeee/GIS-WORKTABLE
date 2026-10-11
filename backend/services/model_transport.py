"""Use configured proxies, ignoring only unreachable loopback system proxies."""
import socket
import urllib.request
from urllib.parse import urlsplit


def effective_model_proxy(url):
    from backend.services.tools import get_proxy_config
    custom = get_proxy_config()
    if custom:
        return custom
    target = urlsplit(url)
    if target.hostname and urllib.request.proxy_bypass(target.hostname):
        return None
    proxies = urllib.request.getproxies()
    proxy = proxies.get(target.scheme) or proxies.get('all')
    if not proxy:
        return None
    parsed = urlsplit(proxy if '://' in proxy else 'http://' + proxy)
    if parsed.hostname in ('localhost', '127.0.0.1', '::1'):
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.3):
                pass
        except OSError:
            return None
    return proxy
