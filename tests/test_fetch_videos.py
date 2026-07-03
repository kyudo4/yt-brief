"""Kryterium akceptacji: Shorts i filmy <= 5 min nie przechodzą filtra."""

from src.fetch_videos import parse_duration, passes_filter


def test_short_60s_odpada():
    assert not passes_filter(parse_duration("PT60S"))


def test_film_dokladnie_5_min_odpada():
    assert not passes_filter(parse_duration("PT5M"))


def test_film_5_min_1s_przechodzi():
    assert passes_filter(parse_duration("PT5M1S"))


def test_dlugi_film_przechodzi():
    assert passes_filter(parse_duration("PT1H12M30S"))


def test_live_bez_czasu_odpada():
    # transmisje live mają duration 'P0D' — parsujemy jako 0, odpada
    assert not passes_filter(parse_duration("P0D"))


def test_parse_duration():
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("PT15M") == 900
    assert parse_duration("PT45S") == 45
