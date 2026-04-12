from reddit_avatar.config import TopicConfig


def test_load_example_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("""
topic: "test"
subreddits: [selfhosted]
limits: {posts_per_sub: 10}
""")
    cfg = TopicConfig.load(p)
    assert cfg.topic == "test"
    assert cfg.limits.posts_per_sub == 10
    assert cfg.fingerprint()  # stable hash
