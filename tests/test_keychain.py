import pytest

from fourg_bridge.storage.keychain import KeychainError, KeychainStore


class SecurityFixture:
    kSecClass = "class"
    kSecClassGenericPassword = "generic"
    kSecAttrService = "service"
    kSecAttrAccount = "account"
    kSecReturnData = "return_data"
    kSecMatchLimit = "limit"
    kSecMatchLimitOne = "one"
    kSecUseAuthenticationUI = "authentication_ui"
    kSecUseAuthenticationUIFail = "fail_without_ui"
    errSecItemNotFound = -25300
    errSecSuccess = 0

    def __init__(self, status=0):
        self.status = status
        self.query = None
        self.interactions = []

    def SecKeychainGetUserInteractionAllowed(self, _state):
        return 0, True

    def SecKeychainSetUserInteractionAllowed(self, state):
        self.interactions.append(state)
        return 0

    def SecItemCopyMatching(self, query, _result):
        self.query = query
        return self.status, b"test@example.invalid"


def test_background_keychain_read_cannot_open_authorization_dialog():
    security = SecurityFixture()
    assert KeychainStore(security).get_target() == "test@example.invalid"
    assert security.query[security.kSecUseAuthenticationUI] == security.kSecUseAuthenticationUIFail
    assert security.interactions == [False, True]


def test_only_explicit_authorization_allows_keychain_dialog():
    security = SecurityFixture()
    assert KeychainStore(security).get_target(allow_interaction=True)
    assert security.kSecUseAuthenticationUI not in security.query


def test_keychain_locked_and_missing_are_distinct():
    assert KeychainStore(SecurityFixture(-25300)).get_target() is None
    with pytest.raises(KeychainError):
        KeychainStore(SecurityFixture(-25308)).get_target()
