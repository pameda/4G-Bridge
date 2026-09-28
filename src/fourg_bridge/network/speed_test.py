"""Bounded, cancellable HTTPS measurements; no files, telemetry or network mutations."""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from ipaddress import IPv4Address
from itertools import pairwise


class TestMode(StrEnum):
    WIFI = "wifi"
    CURRENT = "current"
    CELLULAR = "cellular"


@dataclass(frozen=True)
class TestPlan:
    name: str
    download: int
    upload: int

    @property
    def payload(self) -> int:
        return self.download + self.upload


PLANS = (TestPlan("轻量", 8 * 1024**2, 2 * 1024**2), TestPlan("标准", 32 * 1024**2, 8 * 1024**2))


@dataclass(frozen=True)
class SpeedState:
    phase: str = "ready"
    note: str = "选择网络后开始；不会自动测速或开启 4G。"
    progress: float = 0
    download_mbps: float | None = None
    upload_mbps: float | None = None
    latency_ms: float | None = None
    jitter_ms: float | None = None
    payload_bytes: int = 0
    route: str = "尚未测速"
    elapsed: float = 0

    @property
    def running(self) -> bool:
        return self.phase in ("latency", "download", "upload")


@dataclass(frozen=True)
class Measurement:
    downloaded: int
    uploaded: int
    seconds: float
    ttfb: float


class SpeedFailure(Exception):
    """Only fixed public diagnostics may reach the UI."""


class SpeedCancelled(SpeedFailure):
    pass


def measurement(output: bytes, expected_down: int, expected_up: int) -> Measurement:
    try:
        fields = output.decode("ascii").strip().split()
        if len(fields) != 5 or fields[0] != "200":
            raise ValueError
        values = [float(value) for value in fields[1:]]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError
        down, up, seconds, ttfb = values
        if seconds <= 0 or ttfb > seconds:
            raise ValueError
        # Detect partial transfers and small error pages, never report them as bandwidth.
        if down != expected_down or up != expected_up:
            raise ValueError
        return Measurement(int(down), int(up), seconds, ttfb)
    except (UnicodeError, ValueError, OverflowError):
        raise SpeedFailure("测速响应不完整或格式异常，没有生成虚假的速率。") from None


def curl_arguments(kind: str, count: int, interface: str | None) -> list[str]:
    if kind not in ("latency", "download", "upload") or not 0 <= count <= 32 * 1024**2:
        raise ValueError("Invalid measurement")
    if interface is not None and not re.fullmatch(r"en[0-9]{1,3}", interface):
        raise ValueError("Invalid physical interface")
    args = [
        "/usr/bin/curl",
        "-q",
        "--silent",
        "--fail",
        "--noproxy",
        "*",
        "--proto",
        "=https",
        "--tlsv1.2",
        "--connect-timeout",
        "5",
        "--max-time",
        "15",
        "--max-filesize",
        str(max(count if kind == "download" else 0, 1024)),
        "--output",
        "/dev/null",
        "--header",
        "Cache-Control: no-store",
        "--write-out",
        "%{http_code} %{size_download} %{size_upload} %{time_total} %{time_starttransfer}",
    ]
    if interface:
        args += ["--interface", f"if!{interface}"]
    if kind == "upload":
        args += [
            "--request",
            "POST",
            "--header",
            "Content-Type: application/octet-stream",
            "--header",
            "Expect:",
            "--data-binary",
            "@-",
            "https://speed.cloudflare.com/__up",
        ]
    else:
        args += [f"https://speed.cloudflare.com/__down?bytes={count}"]
    return args


def resolved_address(output: bytes) -> str:
    """Accept a bounded DNS response only for our fixed public measurement host."""
    try:
        if len(output) > 4096:
            raise ValueError
        data = json.loads(output)
        if data["Status"] != 0 or data.get("TC", False):
            raise ValueError
        questions = data["Question"]
        if (
            len(questions) != 1
            or questions[0]["name"].rstrip(".") != "speed.cloudflare.com"
            or questions[0]["type"] != 1
        ):
            raise ValueError
        for answer in data["Answer"]:
            if answer.get("type") == 1:
                address = IPv4Address(answer["data"])
                if address.is_global:
                    return str(address)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        pass
    raise SpeedFailure("无法取得测速服务的公网地址；未改用其他网络。")


class CurlMeasurement:
    def __init__(self) -> None:
        self.address: str | None = None

    def prepare(
        self, interface: str | None, cancelled: threading.Event, permitted: Callable[[], bool]
    ) -> None:
        self.address = None
        if interface is None:
            return  # Current-network mode intentionally keeps the VPN/system resolver.
        # Resolve the one public test host through the user's current system route.
        # VPN fake-IP endpoints are reachable there; payload transfers stay bound.
        # This is not a system DNS change or an alternate payload route.
        args = curl_arguments("download", 4096, None)
        args[args.index("--output") + 1] = "-"
        write_index = args.index("--write-out")
        del args[write_index : write_index + 2]
        args[-1:] = [
            "--header",
            "Accept: application/dns-json",
            "https://cloudflare-dns.com/dns-query?name=speed.cloudflare.com&type=A",
        ]
        try:
            self.address = resolved_address(self._capture(args, None, cancelled, permitted))
        except SpeedCancelled:
            raise
        except SpeedFailure:
            raise SpeedFailure("测速域名解析不可达或响应无效；未开始下载或上传。") from None

    def perform(
        self,
        kind: str,
        count: int,
        interface: str | None,
        cancelled: threading.Event,
        permitted: Callable[[], bool],
    ) -> Measurement:
        if cancelled.is_set() or not permitted():
            raise SpeedCancelled("已停止：网络或套餐状态改变，或你取消了测速。")
        args = curl_arguments(kind, count, interface)
        if interface and self.address:
            args[-1:-1] = ["--resolve", f"speed.cloudflare.com:443:{self.address}"]
        payload = os.urandom(count) if kind == "upload" else None
        output = self._capture(args, payload, cancelled, permitted)
        # Upload service returns a small numeric server-time body, not user data.
        if kind == "upload":
            fields = output.split()
            if len(fields) != 5 or not fields[1].isdigit() or int(fields[1]) > 1024:
                raise SpeedFailure("上传响应异常，测速已停止。")
            expected_down = int(fields[1])
        else:
            expected_down = count
        return measurement(output, expected_down, count if kind == "upload" else 0)

    @staticmethod
    def _capture(
        args: list[str],
        payload: bytes | None,
        cancelled: threading.Event,
        permitted: Callable[[], bool],
    ) -> bytes:
        if cancelled.is_set() or not permitted():
            raise SpeedCancelled("已停止：网络或套餐状态改变，或你取消了测速。")
        # No shell, curlrc, redirects, proxy environment, uploads of files, or raw stderr logs.
        with subprocess.Popen(
            args,
            stdin=subprocess.PIPE if payload else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        ) as child:
            deadline = time.monotonic() + 17
            try:
                while True:
                    if not permitted() or cancelled.is_set():
                        raise SpeedCancelled("已停止：网络或套餐状态改变，或你取消了测速。")
                    if time.monotonic() > deadline:
                        raise SpeedFailure("测速超时；没有自动重试，也没有切换网络。")
                    try:
                        output, _ = child.communicate(input=payload, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        payload = None  # communicate retains the original input across timeouts.
                if child.returncode:
                    raise SpeedFailure(
                        "无法完成测速：服务不可达、连接超时或网络受限。可稍后手动重试。"
                    )
                return output
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate()


class SpeedTest:
    def __init__(self, transport: CurlMeasurement | None = None):
        self.transport = transport or CurlMeasurement()

    def run(
        self,
        plan: TestPlan,
        interface: str | None,
        route: str,
        cancelled: threading.Event,
        permitted: Callable[[], bool],
        publish: Callable[[SpeedState], None],
    ) -> SpeedState:
        if plan not in PLANS:
            raise ValueError("Unknown test plan")
        started = time.monotonic()
        state = SpeedState(phase="latency", note="正在准备测速线路与域名解析…", route=route)
        publish(state)
        try:
            self.transport.prepare(interface, cancelled, permitted)
            state = replace(state, note="正在测量 HTTPS 首字节延迟…")
            publish(state)
            latencies = []
            for i in range(3):
                result = self.transport.perform("latency", 0, interface, cancelled, permitted)
                latencies.append(result.ttfb * 1000)
                state = replace(state, progress=(i + 1) * 0.05)
                publish(state)
            state = replace(
                state,
                phase="download",
                note="正在测量下载速率…",
                latency_ms=statistics.median(latencies),
                jitter_ms=statistics.mean(abs(b - a) for a, b in pairwise(latencies)),
            )
            publish(state)
            down = self.transport.perform(
                "download", plan.download, interface, cancelled, permitted
            )
            state = replace(
                state,
                phase="upload",
                note="正在测量上传速率…",
                progress=0.65,
                download_mbps=down.downloaded * 8 / down.seconds / 1_000_000,
                payload_bytes=down.downloaded,
            )
            publish(state)
            up = self.transport.perform("upload", plan.upload, interface, cancelled, permitted)
            state = replace(
                state,
                phase="complete",
                note="测速完成 · 单连接结果，不代表线路峰值。",
                progress=1,
                upload_mbps=up.uploaded * 8 / up.seconds / 1_000_000,
                payload_bytes=state.payload_bytes + up.uploaded + up.downloaded,
            )
        except SpeedCancelled as error:
            state = replace(state, phase="cancelled", note=str(error))
        except SpeedFailure as error:
            state = replace(state, phase="failed", note=str(error))
        except (OSError, subprocess.SubprocessError):
            state = replace(
                state, phase="failed", note="测速未完成：服务不可达、超时或响应异常；不自动重试。"
            )
        state = replace(state, elapsed=time.monotonic() - started)
        publish(state)
        return state
