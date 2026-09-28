from fourg_bridge.support.presentation import relay_switch_label


def test_switch_status_is_not_delivery_health():
    assert relay_switch_label(True) == "已开启"
    assert relay_switch_label(False) == "已关闭"
    assert relay_switch_label(True, paused=True) == "已暂停"
    assert relay_switch_label(False, paused=True) == "已暂停"
