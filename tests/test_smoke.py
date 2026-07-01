"""冒烟测试：确认包可导入。"""


def test_import_package():
    import flowmind

    assert flowmind is not None
