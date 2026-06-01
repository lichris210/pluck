import pytest
from pluck.url_keys import schema_key, results_key


# ── schema_key ────────────────────────────────────────────────────────────────

class TestSchemaKey:
    def test_trailing_slash_normalised(self):
        assert schema_key("https://example.com/jobs/") == schema_key("https://example.com/jobs")

    def test_numeric_id_collapsed(self):
        assert schema_key("https://linkedin.com/jobs/12345") == "linkedin.com/jobs/*"

    def test_two_different_job_ids_same_schema_key(self):
        assert schema_key("https://linkedin.com/jobs/11111") == schema_key("https://linkedin.com/jobs/99999")

    def test_semantic_segment_preserved(self):
        key = schema_key("https://linkedin.com/jobs/search")
        assert key == "linkedin.com/jobs/search"

    def test_uuid_like_id_collapsed(self):
        assert schema_key("https://example.com/items/a3f9c2d1e4b5") == "example.com/items/*"

    def test_www_subdomain_stripped(self):
        assert schema_key("https://www.linkedin.com/jobs/123") == schema_key("https://linkedin.com/jobs/123")

    def test_other_subdomain_preserved(self):
        key = schema_key("https://api.example.com/data")
        assert key == "api.example.com/data"

    def test_fragment_dropped(self):
        assert schema_key("https://example.com/jobs#section") == "example.com/jobs"

    def test_query_params_dropped(self):
        assert schema_key("https://example.com/search?q=python") == "example.com/search"

    def test_long_opaque_slug_collapsed(self):
        slug = "aBcDeFgHiJkLmNoPqRsT"  # 20 chars
        assert schema_key(f"https://example.com/posts/{slug}") == "example.com/posts/*"


# ── results_key ───────────────────────────────────────────────────────────────

class TestResultsKey:
    def test_trailing_slash_normalised(self):
        assert results_key("https://example.com/page/") == results_key("https://example.com/page")

    def test_query_params_reordered_identical(self):
        a = results_key("https://example.com/search?b=2&a=1")
        b = results_key("https://example.com/search?a=1&b=2")
        assert a == b

    def test_query_params_sorted_output(self):
        key = results_key("https://example.com/search?z=3&a=1&m=2")
        assert key == "example.com/search?a=1&m=2&z=3"

    def test_fragment_dropped(self):
        assert results_key("https://example.com/page#section") == "example.com/page"

    def test_scheme_stripped(self):
        key = results_key("https://example.com/page")
        assert not key.startswith("http")

    def test_two_job_ids_different_results_key(self):
        assert results_key("https://linkedin.com/jobs/11111") != results_key("https://linkedin.com/jobs/99999")

    def test_www_preserved_in_results_key(self):
        # results_key does NOT strip www — only schema_key does
        key = results_key("https://www.example.com/page")
        assert key == "www.example.com/page"

    def test_non_standard_port_included(self):
        key = results_key("http://localhost:8080/api/data")
        assert "8080" in key

    def test_standard_port_excluded(self):
        assert results_key("https://example.com:443/page") == results_key("https://example.com/page")
