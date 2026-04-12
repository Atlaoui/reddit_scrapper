from reddit_avatar.harvest import _parse_listing, _parse_top_level_comments


def test_parse_listing_extracts_posts():
    data = {
        "data": {
            "children": [
                {"kind": "t3", "data": {"id": "a1", "title": "T", "subreddit": "x",
                                         "selftext": "body", "permalink": "/r/x/a1/",
                                         "created_utc": 1.0, "score": 3}},
                {"kind": "t1", "data": {"id": "should_skip"}},
            ]
        }
    }
    posts = _parse_listing(data)
    assert len(posts) == 1 and posts[0]["id"] == "a1"


def test_parse_top_level_comments_respects_limit():
    data = [
        {},
        {"data": {"children": [
            {"kind": "t1", "data": {"id": "c1", "body": "one", "score": 1, "author": "a"}},
            {"kind": "t1", "data": {"id": "c2", "body": "two", "score": 2, "author": "b"}},
            {"kind": "t1", "data": {"id": "c3", "body": "three", "score": 3, "author": "c"}},
            {"kind": "more", "data": {}},
        ]}},
    ]
    out = _parse_top_level_comments(data, limit=2)
    assert [c.id for c in out] == ["c1", "c2"]


def test_parse_top_level_comments_handles_empty():
    assert _parse_top_level_comments([], 5) == []
    assert _parse_top_level_comments([{}], 5) == []
