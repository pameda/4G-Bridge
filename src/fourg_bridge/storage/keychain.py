from __future__ import annotations

import threading
from typing import Any


class KeychainError(RuntimeError):
    pass


class KeychainStore:
    SERVICE = "com.pameda.fourgbridge"
    ACCOUNT = "imessage-relay-target"
    _interaction_lock = threading.RLock()

    def __init__(self, security: Any | None = None) -> None:
        self._security = security

    def get_target(self, *, allow_interaction: bool = False) -> str | None:
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
        return bytes(result).decode("utf-8")

    def set_target(self, target: str) -> None:
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
        status = security.SecItemUpdate(selector, {security.kSecValueData: value.encode()})
        if status == security.errSecItemNotFound:
            item = {**selector, security.kSecValueData: value.encode()}
            status, _ = security.SecItemAdd(item, None)
        if status != security.errSecSuccess:
            raise KeychainError(f"Keychain write failed: {status}")

    def delete_target(self) -> None:
        security = self._framework()
        query = {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.SERVICE,
            security.kSecAttrAccount: self.ACCOUNT,
        }
        status = security.SecItemDelete(query)
        if status not in (security.errSecSuccess, security.errSecItemNotFound):
            raise KeychainError(f"Keychain delete failed: {status}")

    def _framework(self) -> Any:
        if self._security is not None:
            return self._security
        import Security  # type: ignore[import-untyped]

        return Security
