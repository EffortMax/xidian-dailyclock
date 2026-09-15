from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import xidian_login as xl

from app.services.credential_store import (
    CredentialStore,
    CredentialStoreError,
    SavedCredentials,
)


LogCallback = Callable[[str], None]
CaptchaProvider = Callable[[bytes, int], str]


def default_data_dir() -> Path:
    """返回不在项目目录中的本地应用数据目录。"""

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / ".local" / "share")
    path = Path(base) / "DailyClockXDU"
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        # 受限运行环境或权限策略下的可用回退；目录已加入 .gitignore。
        fallback = Path(__file__).resolve().parents[2] / "app_state"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class AuthService:
    """统一管理登录、Cookie 和验证码策略。"""

    def __init__(self, log: LogCallback | None = None) -> None:
        self.log = log or (lambda _message: None)
        self.session = None
        self.user_id = ""
        self._password = ""
        self.unattended = False
        self.manual_captcha_provider: CaptchaProvider | None = None
        data_dir = default_data_dir()
        self.cookie_file = data_dir / "cookies.json"
        self.captcha_file = data_dir / "captcha.jpg"
        self.credential_store = CredentialStore(data_dir / "credentials.json")

    def set_unattended(self, value: bool) -> None:
        self.unattended = bool(value)

    def set_manual_captcha_provider(self, provider: CaptchaProvider | None) -> None:
        """设置桌面端人工验证码回调，避免后台线程读取终端 stdin。"""

        self.manual_captcha_provider = provider

    def _captcha_provider(self):
        if not self.unattended:
            return self.manual_captcha_provider
        provider = xl.make_ddddocr_provider(verbose=False)
        if provider is None:
            raise RuntimeError(
                "已开启无人值守，但未安装 ddddocr。请先安装依赖，或关闭无人值守模式。"
            )
        return provider

    def load_saved_credentials(self) -> SavedCredentials | None:
        try:
            return self.credential_store.load()
        except CredentialStoreError as exc:
            self.log("读取已保存账户失败：{0}".format(exc))
            return None

    def _update_saved_credentials(
        self,
        user_id: str,
        password: str,
        remember_credentials: bool,
    ) -> None:
        try:
            if remember_credentials:
                self.credential_store.save(user_id, password)
                self.log("账户和密码已使用 Windows DPAPI 加密保存")
            else:
                self.credential_store.clear()
        except CredentialStoreError as exc:
            self.log("保存账户设置失败：{0}".format(exc))

    def login(
        self,
        user_id: str,
        password: str,
        force: bool = False,
        remember_credentials: bool = False,
    ):
        user_id = user_id.strip()
        if not user_id or not password:
            raise ValueError("学号和密码不能为空")

        # ask_captcha 使用模块级路径；桌面应用把验证码放到用户数据目录。
        xl.CAPTCHA_FILE = str(self.captcha_file)
        self.user_id = user_id
        self._password = password
        provider = self._captcha_provider()
        self.session = xl.ensure_session(
            user_id,
            password,
            cookie_file=str(self.cookie_file),
            force_login=force,
            captcha_provider=provider,
            strict=True,
        )
        ok, why = xl.login_state(self.session)
        if ok is not True:
            raise xl.LoginError("登录状态复核失败：{0}".format(why))
        self._update_saved_credentials(user_id, password, remember_credentials)
        self.log("登录状态已确认：{0}".format(why))
        return self.session

    def relogin(self):
        if not self.session or not self.user_id or not self._password:
            raise xl.LoginError("没有可用于重新登录的会话信息")
        provider = self._captcha_provider()
        self.session = xl.relogin(
            self.session,
            self.user_id,
            self._password,
            cookie_file=str(self.cookie_file),
            captcha_provider=provider,
        )
        ok, why = xl.login_state(self.session)
        if ok is not True:
            raise xl.LoginError("重新登录后状态复核失败：{0}".format(why))
        self.log("会话恢复成功：{0}".format(why))
        return self.session

    def require_session(self):
        if self.session is None:
            raise RuntimeError("请先登录选课系统")
        return self.session
