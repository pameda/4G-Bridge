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
    kSecValueData = "data"

    def __init__(self, status=0):
        self.status = status
        self.query = None
        self.interactions = []
        self.reads = 0

    def SecKeychainGetUserInteractionAllowed(self, _state):
        return 0, True

    def SecKeychainSetUserInteractionAllowed(self, state):
        self.interactions.append(state)
        return 0

    def SecItemCopyMatching(self, query, _result):
        self.reads += 1
        self.query = query
        return self.status, b"test@example.invalid"

    def SecItemUpdate(self, query, values):
        return self.status

    def SecItemAdd(self, item, result):
        return 0, None

    def SecItemDelete(self, query):
        return self.status


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


def test_allow_once_is_reused_by_refresh_check_and_background_relay():
    security = SecurityFixture()
    store = KeychainStore(security)
    assert store.get_target(allow_interaction=True) == "test@example.invalid"
    security.status = -25308
    for _ in range(3):
        assert store.get_target() == "test@example.invalid"
    assert security.reads == 1
    store.clear_session_target()
    with pytest.raises(KeychainError):
        store.get_target()


def test_failed_reauthorization_does_not_reuse_old_target():
    security = SecurityFixture()
    store = KeychainStore(security)
    store.get_target(allow_interaction=True)
    security.status = -25308
    with pytest.raises(KeychainError):
        store.get_target(allow_interaction=True)
    with pytest.raises(KeychainError):
        store.get_target()


def test_sleep_during_authorization_cannot_restore_cached_target():
    security = SecurityFixture()
    store = KeychainStore(security)

    def read(query, result):
        store.clear_session_target()
        return 0, b"test@example.invalid"

    security.SecItemCopyMatching = read
    with pytest.raises(KeychainError, match="cancelled"):
        store.get_target(allow_interaction=True)
    assert store._session_target is None


@pytest.mark.parametrize("status", [0, -25300])
def test_save_caches_target_and_delete_clears_it(status):
    security = SecurityFixture(status)
    store = KeychainStore(security)
    store.set_target("new@example.invalid")
    assert store.get_target() == "new@example.invalid"
    assert security.reads == 0
    store.delete_target()
    assert store._session_target is None
    assert security.interactions == [True, True, True, True]


def test_failed_write_invalidates_old_cache_and_restores_policy():
    security = SecurityFixture()
    store = KeychainStore(security)
    store.get_target(allow_interaction=True)
    security.status = -25308
    with pytest.raises(KeychainError):
        store.set_target("new@example.invalid")
    assert store._session_target is None
    assert security.interactions[-2:] == [True, True]
