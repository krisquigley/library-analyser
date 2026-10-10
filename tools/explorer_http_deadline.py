"""Absolute-deadline HTTP transport for the diagnostic's numeric loopback URL.

This outward transport detail does not change Explorer's HTTP server. A shared
monotonic budget is applied at the socket boundary, including the repeated raw
reads used by HTTP header parsing (not just reads of the response body).
"""
from http.client import HTTPConnection
import socket
import time
from urllib.request import HTTPHandler


class RequestDeadline:
    def __init__(self, start, timeout):
        self.end = start + timeout

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('HTTP request deadline expired')
        return remaining


class _DeadlineSocket(socket.socket):
    def __init__(self, connected, deadline):
        # Transfer ownership; socket.makefile/SocketIO retain this socket using
        # the standard socket lifecycle, so closing HTTPResponse closes its fd.
        super().__init__(connected.family, connected.type, connected.proto,
                         fileno=connected.detach())
        self.deadline = deadline

    def recv_into(self, buffer, nbytes=0, flags=0):
        self.settimeout(self.deadline.remaining())
        return super().recv_into(buffer, nbytes, flags)

    def sendall(self, data, flags=0):
        # socket.sendall's timeout bounds the complete send, not each write.
        self.settimeout(self.deadline.remaining())
        return super().sendall(data, flags)


class _DeadlineConnection(HTTPConnection):
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline

    def connect(self):
        # Built-in requests use a numeric 127.0.0.1 address: no remote DNS or
        # multi-address discovery. Connection time consumes this same budget.
        self.timeout = self.deadline.remaining()
        super().connect()
        try:
            self.deadline.remaining()
            self.sock = _DeadlineSocket(self.sock, self.deadline)
        except BaseException:
            self.close()
            raise


class DeadlineHTTPHandler(HTTPHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def http_open(self, request):
        def connection(host, **kwargs):
            return _DeadlineConnection(host, deadline=self.deadline, **kwargs)
        return self.do_open(connection, request)
