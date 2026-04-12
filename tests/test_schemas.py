from reddit_avatar.schemas import ExtractedSignals, Quote


def test_extracted_signals_defaults_empty():
    s = ExtractedSignals()
    assert s.pains == [] and s.verbatim_quotes == []


def test_quote_roundtrip():
    q = Quote(text="it just works", post_id="abc123")
    assert q.model_dump()["post_id"] == "abc123"
