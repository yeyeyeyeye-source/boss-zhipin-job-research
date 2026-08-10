"""Dedicated Chrome lifecycle and user-facing login-state mapping."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from scripts import boss_cdp_raw as core

from .db import Database, utc_now


class LoginStatus(Enum):
    UNCONFIGURED = "未配置"
    CHROME_NOT_RUNNING = "Chrome未启动"
    WAITING_FOR_LOGIN = "等待登录"
    LOGGED_IN = "已登录"
    EXPIRED = "登录失效"
    RESTRICTED = "访问受限"
    UNKNOWN = "状态未知"


@dataclass(frozen=True)
class LoginState:
    status: LoginStatus
    message: str = ""


class LoginManager:
    def __init__(
        self,
        database: Database,
        cdp_port: int = core.DEFAULT_CDP_PORT,
        request_budget=None,
    ):
        self.database = database
        self.cdp_port = cdp_port
        self.request_budget = request_budget

    def recently_logged_in(self, max_age_seconds: int = 30) -> bool:
        value = self.database.get_state("last_login_success_at")
        if not value:
            return False
        try:
            timestamp = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        return 0 <= age <= max(1, int(max_age_seconds))

    def status(self, probe: bool = True, allow_recent: bool = False) -> LoginState:
        if not Path(core.DEFAULT_CHROME_PATH).exists():
            return LoginState(LoginStatus.UNCONFIGURED, f"未找到 Chrome: {core.DEFAULT_CHROME_PATH}")
        if not Path(core.DEFAULT_CDP_DATA_DIR).expanduser().exists():
            return LoginState(LoginStatus.UNCONFIGURED, "尚未创建 BOSS 专用 Chrome Profile")
        if not core.require_runtime_dependencies("requests"):
            return LoginState(LoginStatus.UNKNOWN, "缺少 requests 依赖")
        if not core.is_cdp_ready(self.cdp_port):
            return LoginState(LoginStatus.CHROME_NOT_RUNNING, f"CDP 端口 {self.cdp_port} 未启动")
        if allow_recent and self.recently_logged_in():
            return LoginState(LoginStatus.LOGGED_IN, "复用刚完成的 BOSS 登录检查")
        if not probe:
            return LoginState(LoginStatus.UNKNOWN, "Chrome 已启动，尚未执行登录探测")
        result = core.check_login_state(
            self.cdp_port,
            request_budget=self.request_budget,
        )
        if result.status is core.LoginProbeStatus.AVAILABLE:
            self.database.set_state("last_login_success_at", utc_now())
            return LoginState(LoginStatus.LOGGED_IN, "BOSS 登录态可用")
        if result.status is core.LoginProbeStatus.RESTRICTED:
            return LoginState(LoginStatus.RESTRICTED, core.describe_login_probe_result(result))
        if result.status is core.LoginProbeStatus.UNAUTHENTICATED:
            if self.database.get_state("last_login_success_at"):
                return LoginState(LoginStatus.EXPIRED, core.describe_login_probe_result(result))
            return LoginState(LoginStatus.WAITING_FOR_LOGIN, core.describe_login_probe_result(result))
        return LoginState(LoginStatus.UNKNOWN, core.describe_login_probe_result(result))

    def open_login_browser(self) -> subprocess.Popen:
        """Start the existing setup command without waiting inside Streamlit."""
        script = Path(core.__file__).resolve()
        command = [
            sys.executable, str(script), "--setup-chrome", "--no-wait-login",
            "--cdp-port", str(self.cdp_port),
        ]
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if platform.system() == "Windows":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(command, **kwargs)
