from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class KeychainError(RuntimeError):
    pass


class KeychainStore:
    SERVICE = "com.pameda.fourgbridge"
    ACCOUNT = "imessage-relay-target"
    _interaction_lock = threading.RLock()

    def __init__(self, security: Any | None = None) -> None:
        self._security = security
        self._cache_lock = threading.Lock()
        self._session_target: str | None = None
        self._epoch = 0

    def clear_session_target(self) -> None:
        """Forget explicit one-time authorization without changing keychain ACLs."""
        with self._cache_lock:
            self._session_target = None
            self._epoch += 1

    def get_target(self, *, allow_interaction: bool = False) -> str | None:
        if allow_interaction:
            self.clear_session_target()
        with self._cache_lock:
            if not allow_interaction and self._session_target is not None:
                return self._session_target
            epoch = self._epoch
        security = self._framework()
        query = {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.SERVICE,
            security.kSecAttrAccount: self.ACCOUNT,
            security.kSecReturnData: True,
            security.kSecMatchLimit: security.kSecMatchLimitOne,
        }
        if not allow_interaction:
            query[security.kSecUseAuthenticationUI] = security.kSecUseAuthenticationUIFail
        # Legacy login-keychain ACL prompts do not honor the data-protection
        # kSecUseAuthenticationUI key on every macOS version. Serialize the
        # process-wide legacy flag and never let a background read wait for UI.
        if not self._interaction_lock.acquire(blocking=allow_interaction):
            raise KeychainError("Keychain authorization is busy")
        try:
            status, previous = security.SecKeychainGetUserInteractionAllowed(None)
            if status != security.errSecSuccess:
                raise KeychainError("Cannot read keychain interaction policy")
            status = security.SecKeychainSetUserInteractionAllowed(allow_interaction)
            if status != security.errSecSuccess:
                raise KeychainError("Cannot set keychain interaction policy")
            try:
                status, result = security.SecItemCopyMatching(query, None)
            finally:
                security.SecKeychainSetUserInteractionAllowed(previous)
        finally:
            self._interaction_lock.release()
        if status == security.errSecItemNotFound:
            return None
        if status != security.errSecSuccess:
            raise KeychainError(f"Keychain read failed: {status}")
        value = bytes(result).decode("utf-8")
        if allow_interaction:
            with self._cache_lock:
                if epoch != self._epoch:
                    raise KeychainError("Keychain authorization was cancelled")
                # "Allow once" belongs to this app session. Never persist plaintext
                # or ask the OS to weaken the item's access controls.
                self._session_target = value
        return value

    def set_target(self, target: str) -> None:
        self.clear_session_target()
        with self._cache_lock:
            epoch = self._epoch
        value = target.strip()
        if not value:
            self.delete_target()
            return
        security = self._framework()
        selector = {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.SERVICE,
            security.kSecAttrAccount: self.ACCOUNT,
        }

        def update() -> int:
            status = security.SecItemUpdate(selector, {security.kSecValueData: value.encode()})
            if status == security.errSecItemNotFound:
                item = {**selector, security.kSecValueData: value.encode()}
                status, _ = security.SecItemAdd(item, None)
            return int(status)

        self._mutate(update)
        with self._cache_lock:
            if epoch == self._epoch:
                self._session_target = value

    def delete_target(self) -> None:
        self.clear_session_target()
        security = self._framework()
        query = {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.SERVICE,
            security.kSecAttrAccount: self.ACCOUNT,
        }
        self._mutate(lambda: int(security.SecItemDelete(query)), missing_ok=True)

    def _mutate(self, operation: Callable[[], int], *, missing_ok: bool = False) -> None:
        security = self._framework()
        with self._interaction_lock:
            status, previous = security.SecKeychainGetUserInteractionAllowed(None)
            if status != security.errSecSuccess:
                raise KeychainError("Cannot read keychain interaction policy")
            if security.SecKeychainSetUserInteractionAllowed(True) != security.errSecSuccess:
                raise KeychainError("Cannot set keychain interaction policy")
            try:
                status = operation()
            finally:
                security.SecKeychainSetUserInteractionAllowed(previous)
        if status != security.errSecSuccess and not (
            missing_ok and status == security.errSecItemNotFound
        ):
            raise KeychainError(f"Keychain update failed: {status}")

    def _framework(self) -> Any:
        if self._security is not None:
            return self._security
        import Security  # type: ignore[import-untyped]

        return Security
