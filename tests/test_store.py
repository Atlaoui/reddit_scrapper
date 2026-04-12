from reddit_avatar.schemas import Comment, ExtractedSignals, Post, Quote
from reddit_avatar.store import Store


def test_roundtrip_post_and_signal(tmp_path):
    db = tmp_path / "t.db"
    store = Store(db)
    run_id = store.start_run("topic", "abc")
    store.upsert_post(Post(
        id="p1", subreddit="test", title="t", body="b", author="u",
        score=1, url="https://reddit.com/p1", created_utc=0.0,
        comments=[Comment(id="c1", body="hi", score=1, author="z")],
    ))
    sig = ExtractedSignals(pains=["slow"], verbatim_quotes=[Quote(text="hi", post_id="p1")])
    store.save_signal("p1", run_id, sig, "v1")
    assert store.has_signal("p1", "v1")
    recs = store.signals_for_run(run_id)
    assert len(recs) == 1 and recs[0][1] == "p1"
    got = store.get_post("p1")
    assert got and got.title == "t" and len(got.comments) == 1
    store.close()


def test_run_cost_tracking(tmp_path):
    store = Store(tmp_path / "c.db")
    rid = store.start_run("x", "h")
    store.add_cost(rid, 0.25)
    store.add_cost(rid, 0.10)
    assert abs(store.run_cost(rid) - 0.35) < 1e-9
    store.close()
