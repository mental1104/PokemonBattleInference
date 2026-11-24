#!/usr/bin/env python3
"""为 Swift 更新验收提供真实本机 HTTP 故障服务，不连接生产地址。"""

from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import threading
import time
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import urlsplit


class Scenario(str, Enum):
    """固定下载场景；仅影响 HTTP 传输，不替代 Swift 安装与 SQLite 校验。"""

    GOOD = "good"
    DROP = "drop"
    SLOW = "slow"
    CORRUPT = "corrupt"
    OVERSIZE = "oversize"
    REDIRECT = "redirect"
    MISSING = "missing"
    NO_RANGE = "no-range"


class FixtureServer(ThreadingHTTPServer):
    """独占测试目录与故障计数；锁保护跨请求的首次断线标志和审计追加。"""

    daemon_threads = True

    def __init__(self, directory: Path, audit: Path) -> None:
        """directory 含真实候选包，audit 保存每次 HTTP 请求的状态及 Range。"""
        self.directory = directory
        self.audit = audit
        self.state_lock = threading.Lock()
        self.dropped = False
        self.release_drop = threading.Event()
        super().__init__(("127.0.0.1", 0), FixtureHandler)

    def server_bind(self) -> None:
        """绑定固定回环地址并记录端口；本机验收不需要 HTTPServer 的反向 DNS 查询。"""
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def record(self, path: str, byte_range: str | None, status: int) -> None:
        """追加 path/Range/status 协议证据，文件位于本测试拥有的目录。"""
        with self.state_lock, self.audit.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"path": path, "range": byte_range, "status": status}) + "\n")


class FixtureHandler(BaseHTTPRequestHandler):
    """在真实 TCP 套接字上提供完整、截断、限速和校验错误响应。"""

    server: FixtureServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        """禁用默认 stderr；结构化请求证据统一由 server.record 写入。"""

    def do_POST(self) -> None:
        """父测试确认客户端收到真实前缀后，允许首次 drop 请求关闭真实 TCP 连接。"""
        if urlsplit(self.path).path != "/drop/interrupt":
            self.send_error(404)
            return
        self.server.record(self.path, None, 204)
        self.server.release_drop.set()
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        """按 URL 的场景前缀读取真实文件，支持续传并保留请求审计。"""
        parts = urlsplit(self.path).path.strip("/").split("/")
        try:
            scenario = Scenario(parts[0])
        except (ValueError, IndexError):
            self.send_error(404)
            return
        filename = parts[-1]
        byte_range = self.headers.get("Range")
        if scenario is Scenario.MISSING:
            self.server.record(self.path, byte_range, 404)
            self.send_error(404)
            return
        if scenario is Scenario.REDIRECT:
            self.server.record(self.path, byte_range, 302)
            self.send_response(302)
            self.send_header("Location", "/good/" + filename)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if filename not in {"manifest.json", "knowledge.sqlite"}:
            self.send_error(404)
            return
        content = (self.server.directory / filename).read_bytes()
        if scenario is Scenario.OVERSIZE and filename == "manifest.json":
            content = b"x" * (1024 * 1024 + 1)
        if scenario is Scenario.CORRUPT and filename == "knowledge.sqlite":
            content = content[:100] + bytes([content[100] ^ 255]) + content[101:]
        resume = byte_range is not None and scenario is not Scenario.NO_RANGE
        offset = int(byte_range.removeprefix("bytes=").removesuffix("-")) if byte_range and resume else 0
        status = 206 if resume else 200
        self.server.record(self.path, byte_range, status)
        self.send_response(status)
        self.send_header("Content-Length", str(len(content) - offset))
        self.send_header("Accept-Ranges", "bytes")
        if resume:
            self.send_header("Content-Range", f"bytes {offset}-{len(content) - 1}/{len(content)}")
        self.end_headers()
        with self.server.state_lock:
            drop_now = scenario is Scenario.DROP and filename == "knowledge.sqlite" and not self.server.dropped
            if drop_now:
                self.server.dropped = True
        try:
            if drop_now:
                # 等客户端实际观察到前缀再断开，避免平台在首个delegate回调前丢弃错误响应。
                self.wfile.write(content[offset : offset + 65536])
                self.wfile.flush()
                self.server.release_drop.wait(timeout=10)
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            for index in range(offset, len(content), 8192):
                self.wfile.write(content[index : index + 8192])
                self.wfile.flush()
                if scenario is Scenario.SLOW and filename == "knowledge.sqlite":
                    time.sleep(0.03)
        except (BrokenPipeError, ConnectionResetError):
            # 主动取消是验收场景，连接关闭后不伪造完整发送事件。
            return


def main() -> None:
    """读取自有包/报告路径并启动回环临时端口；父测试终止此进程完成回收。"""
    print("fixture: entered main", file=sys.stderr, flush=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    arguments = parser.parse_args()
    # Linux Swift 从调度线程启动 Process 时可继承被屏蔽的 SIGTERM；夹具显式恢复自己的终止信号。
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
    print("fixture: binding loopback", file=sys.stderr, flush=True)
    with FixtureServer(arguments.directory, arguments.audit) as server:
        # 先写完整地址再原子发布，父进程不能把刚创建的空文件当作就绪握手。
        pending_ready = arguments.ready_file.with_name(f"{arguments.ready_file.name}.pending")
        pending_ready.write_text(f"http://127.0.0.1:{server.server_port}", encoding="ascii")
        pending_ready.replace(arguments.ready_file)
        print("fixture: ready", file=sys.stderr, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
