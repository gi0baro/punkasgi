import urllib.parse

from tonio.colored import net


class ClientDisconnected(OSError): ...


def _socket(stream):
    if isinstance(stream, net.tls.TLSStream):
        stream = stream.transport
    return stream.socket


def get_remote_addr(stream):
    try:
        info = _socket(stream).getpeername()
    except OSError:
        return None
    if isinstance(info, tuple) and len(info) >= 2:
        return (str(info[0]), int(info[1]))
    return None


def get_local_addr(stream):
    try:
        info = _socket(stream).getsockname()
    except OSError:
        return None
    if isinstance(info, tuple) and len(info) >= 2:
        return (str(info[0]), int(info[1]))
    if isinstance(info, str):
        return (info, None)
    return None


def is_ssl(stream):
    return isinstance(stream, net.tls.TLSStream)


def get_client_addr(scope):
    client = scope.get("client")
    if not client:
        return ""
    return "%s:%d" % client


def get_path_with_query_string(scope):
    path_with_query_string = urllib.parse.quote(scope["path"])
    if scope["query_string"]:
        path_with_query_string = "{}?{}".format(path_with_query_string, scope["query_string"].decode("ascii"))
    return path_with_query_string
