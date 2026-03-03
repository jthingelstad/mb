"""Tests for blog reading and category commands."""


class TestBlogPosts:
    def test_get_blog_posts(self, mock_client):
        result = mock_client.get_blog_posts("testuser")
        assert result["ok"] is True
        assert "items" in result["data"]

    def test_get_blog_posts_with_category(self, mock_client):
        result = mock_client.get_blog_posts("testuser", category="notes")
        assert result["ok"] is True


class TestCategories:
    def test_get_categories(self, mock_client):
        result = mock_client.micropub_get_categories()
        assert result["ok"] is True
        assert "categories" in result["data"]
        assert "notes" in result["data"]["categories"]

    def test_get_config(self, mock_client):
        result = mock_client.micropub_get_config()
        assert result["ok"] is True
        destinations = result["data"]["destination"]
        assert len(destinations) == 2
        assert destinations[0]["name"] == "testuser"


class TestSearch:
    def test_search_blog(self, mock_client):
        result = mock_client.search_blog("testuser", query="hello")
        assert result["ok"] is True


class TestMicropubWithCategories:
    def test_create_post_with_categories(self, mock_client):
        result = mock_client.micropub_create(
            content="A note",
            categories=["notes", "preferences"],
        )
        assert result["ok"] is True
        assert "url" in result["data"]
