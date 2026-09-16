from kodimate.windows.base import BaseWindow


def test_init_sets_kwargs_as_attributes():
    window = BaseWindow('x', '/addon', 'Main', '1080i', conn='C', provider_id=7)

    assert window.conn == 'C'
    assert window.provider_id == 7
