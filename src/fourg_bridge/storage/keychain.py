from __future__ import annotations

from typing import Any


class KeychainError(RuntimeError):
    pass


class KeychainStore:
    SERVICE = "com.pameda.fourgbridge"
    ACCOUNT = "imessage-relay-target"

    def __init__(self, security: Any | None = None) -> None:
        self._security = security

    def get_target(self) -> str | None:
        security = self._framework()
        query = {
            security.kSecClass: security.kSecClassGenericPassword,
            security.kSecAttrService: self.SERVICE,
            security.kSecAttrAccount: self.ACCOUNT,
            security.kSecReturnData: True,
            security.kSecMatchLimit: security.kSecMatchLimitOne,
        }
        status, result = security.SecItemCopyMatching(query, None)
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
