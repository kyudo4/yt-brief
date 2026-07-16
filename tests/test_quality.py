from src.quality import review


def test_single_source_requires_human_check():
    report = review({
        "draft_x": {"tekst": "To jest opinia wg Kanał."},
        "kto_co_mowi": [{"kanal": "Kanał"}],
    })
    assert report["status"] == "sprawdz"
    assert report["uwagi"]


def test_missing_source_blocks_draft():
    report = review({"draft_x": {"tekst": "Teza bez źródła."}})
    assert report["status"] == "blokada"


def test_multiple_sources_and_no_warnings_is_ready():
    report = review({
        "draft_x": {"tekst": "To jest komentarz, bez liczbowych twierdzeń."},
        "kto_co_mowi": [{"kanal": "A"}, {"kanal": "B"}],
    })
    assert report["status"] == "gotowy"
