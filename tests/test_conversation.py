"""Tests for conversation thread building."""

from mb.commands.conversation import _build_thread


class TestBuildThread:
    def test_simple_thread(self):
        items = [
            {"id": 100, "_microblog": {}},
            {"id": 101, "_microblog": {"reply_to_id": 100}},
            {"id": 102, "_microblog": {"reply_to_id": 101}},
        ]
        thread = _build_thread(items)
        assert len(thread) == 3
        assert thread[0]["id"] == 100
        assert thread[0]["depth"] == 0
        assert thread[1]["id"] == 101
        assert thread[1]["depth"] == 1
        assert thread[2]["id"] == 102
        assert thread[2]["depth"] == 2

    def test_empty_items(self):
        assert _build_thread([]) == []

    def test_single_post(self):
        items = [{"id": 100, "_microblog": {}}]
        thread = _build_thread(items)
        assert len(thread) == 1
        assert thread[0]["depth"] == 0

    def test_branching_thread(self):
        items = [
            {"id": 100, "_microblog": {}},
            {"id": 101, "_microblog": {"reply_to_id": 100}},
            {"id": 102, "_microblog": {"reply_to_id": 100}},  # second reply to root
        ]
        thread = _build_thread(items)
        assert len(thread) == 3
        assert thread[0]["depth"] == 0
        # Both replies at depth 1
        depths = [t["depth"] for t in thread[1:]]
        assert all(d == 1 for d in depths)
