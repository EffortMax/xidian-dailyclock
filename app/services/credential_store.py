from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


_ENTROPY = b"DailyClockXDU.credentials.v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class CredentialStoreError(RuntimeError):
    """凭据文件或 Windows DPAPI 操作失败。"""


@dataclass(frozen=True)
class SavedCredentials:
    user_id: str
    password: str


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    value = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return value, buffer


class CredentialStore:
    """使用当前 Windows 用户的 DPAPI 加密保存密码。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt" or not hasattr(ctypes, "windll"):
            raise CredentialStoreError("保存密码仅支持 Windows DPAPI")

    @classmethod
    def _protect(cls, plaintext: bytes) -> bytes:
        cls._require_windows()
        source, source_buffer = _blob(plaintext)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DataBlob()
        protect = ctypes.windll.crypt32.CryptProtectData
        protect.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        protect.restype = wintypes.BOOL
        protected = protect(
            ctypes.byref(source),
            "XDU Course Assistant saved password",
            ctypes.byref(entropy),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        # BLOB 只持有指针；显式保持底层缓冲区存活到系统调用结束。
        _ = source_buffer, entropy_buffer
        if not protected:
            raise CredentialStoreError("Windows DPAPI 加密失败：{0}".format(ctypes.WinError()))
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(output.pbData, ctypes.c_void_p))

    @classmethod
    def _unprotect(cls, ciphertext: bytes) -> bytes:
        cls._require_windows()
        source, source_buffer = _blob(ciphertext)
        entropy, entropy_buffer = _blob(_ENTROPY)
        output = _DataBlob()
        unprotect = ctypes.windll.crypt32.CryptUnprotectData
        unprotect.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        unprotect.restype = wintypes.BOOL
        unprotected = unprotect(
            ctypes.byref(source),
            None,
            ctypes.byref(entropy),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        _ = source_buffer, entropy_buffer
        if not unprotected:
            raise CredentialStoreError("Windows DPAPI 解密失败：{0}".format(ctypes.WinError()))
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(ctypes.cast(output.pbData, ctypes.c_void_p))

    def save(self, user_id: str, password: str) -> None:
        if not user_id.strip() or not password:
            raise CredentialStoreError("学号和密码不能为空")
        encrypted = self._protect(password.encode("utf-8"))
        payload = {
            "version": 1,
            "user_id": user_id.strip(),
            "password_dpapi": base64.b64encode(encrypted).decode("ascii"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def load(self) -> SavedCredentials | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != 1:
                raise ValueError("不支持的凭据文件版本")
            user_id = str(payload.get("user_id") or "").strip()
            encrypted = base64.b64decode(payload["password_dpapi"], validate=True)
            password = self._unprotect(encrypted).decode("utf-8")
            if not user_id or not password:
                raise ValueError("凭据内容为空")
            return SavedCredentials(user_id=user_id, password=password)
        except (OSError, KeyError, ValueError, UnicodeError) as exc:
            raise CredentialStoreError("无法读取已保存凭据：{0}".format(exc)) from exc

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
            self.path.with_suffix(self.path.suffix + ".tmp").unlink(missing_ok=True)
        except OSError as exc:
            raise CredentialStoreError("无法删除已保存凭据：{0}".format(exc)) from exc
