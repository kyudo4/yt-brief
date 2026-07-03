from src.topics import _to_seconds


def test_mm_ss():
    assert _to_seconds("02:15") == 135


def test_h_mm_ss():
    assert _to_seconds("1:02:03") == 3723


def test_z_nawiasami():
    assert _to_seconds("[12:00]") == 720


def test_smieci_daja_zero():
    assert _to_seconds("brak") == 0
    assert _to_seconds("") == 0
