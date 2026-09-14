# Uvicorn's multi-worker supervisor creates the listener with `socket.socket(family=family)`,
# so its proto is 0 and asyncio never sets TCP_NODELAY on the accepted connections (its
# `_set_nodelay` requires proto IPPROTO_TCP): every response pays the delayed-ACK stall. Rebuild
# the listener with the TCP proto so the workers get sockets asyncio recognises.
import socket

import uvicorn
import uvicorn.config


_bind_socket = uvicorn.config.Config.bind_socket


def bind_socket(self):
    sock = _bind_socket(self)
    if sock.family in (socket.AF_INET, socket.AF_INET6) and sock.proto != socket.IPPROTO_TCP:
        sock = socket.socket(sock.family, sock.type, socket.IPPROTO_TCP, fileno=sock.detach())
    return sock


uvicorn.config.Config.bind_socket = bind_socket

if __name__ == "__main__":
    uvicorn.main()
