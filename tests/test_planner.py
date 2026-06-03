"""Tests for the intent-aware Apify planner (pluck/registry/planner.py).

Uses the shared `mock_anthropic_client` fixture from conftest. Candidates here
mirror the real registry entries for instagram.com (post + profile) so the
fall-back and username-extraction paths exercise real data shapes.
"""

import json

import pytest

from pluck.registry.planner import (
    _substitute_template,
    _validate_plan,
    plan_extraction,
)

# --- Candidate fixtures (mirror pluck/registry/apify_actors.json) ------------

INSTAGRAM_POST = {
    "domain_patterns": ["instagram.com", "www.instagram.com"],
    "actor_id": "apify/instagram-post-scraper",
    "intent_description": "List posts from an Instagram profile.",
    "input_template": {"directUrls": ["{url}"], "resultsLimit": "{max_items}"},
    "input_notes": "directUrls is an array even for a single URL.",
    "row_unit": "post",
    "default_columns": ["timestamp", "caption", "likesCount", "url"],
    "all_columns": [
        "id",
        "type",
        "caption",
        "hashtags",
        "url",
        "commentsCount",
        "likesCount",
        "timestamp",
        "ownerUsername",
    ],
    "is_default": True,
}

INSTAGRAM_PROFILE = {
    "domain_patterns": ["instagram.com", "www.instagram.com"],
    "actor_id": "apify/instagram-profile-scraper",
    "intent_description": "Get profile-level info for Instagram accounts.",
    "input_template": {"usernames": ["{username}"]},
    "input_notes": "Takes usernames, not URLs.",
    "row_unit": "profile",
    "default_columns": ["username", "biography", "followersCount"],
    "all_columns": [
        "username",
        "fullName",
        "biography",
        "followersCount",
        "postsCount",
        "verified",
    ],
    "is_default": False,
}

INSTAGRAM_CANDIDATES = [INSTAGRAM_POST, INSTAGRAM_PROFILE]
URL = "https://instagram.com/natgeo/"


def _set_response(client, payload):
    """Point the mock client's `messages.create` at a one-block text response."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client.messages.create.return_value = client._make_response(text)


def test_valid_plan_parses_and_validates(mock_anthropic_client):
    """A well-formed plan survives validation with its choices intact."""
    _set_response(
        mock_anthropic_client,
        {
            "actor_id": "apify/instagram-post-scraper",
            "actor_input": {
                "directUrls": ["https://instagram.com/natgeo"],
                "resultsLimit": 12,
            },
            "output_shape": {
                "explode_field": None,
                "columns": ["timestamp", "caption", "likesCount"],
                "rename": {},
            },
            "reasoning": "User asked for posts.",
        },
    )

    plan = plan_extraction(
        URL, "scrape the postings", 50, INSTAGRAM_CANDIDATES,
        mock_anthropic_client,
    )

    assert plan["actor_id"] == "apify/instagram-post-scraper"
    # URL is deterministically substituted (trailing slash stripped).
    assert plan["actor_input"] == {
        "directUrls": ["https://instagram.com/natgeo"],
        "resultsLimit": 12,
    }
    assert plan["output_shape"]["columns"] == [
        "timestamp",
        "caption",
        "likesCount",
    ]
    mock_anthropic_client.messages.create.assert_called_once()


def test_hallucinated_actor_id_falls_back_to_default(mock_anthropic_client):
    """An actor_id absent from candidates triggers retry, then the default."""
    _set_response(
        mock_anthropic_client,
        {
            "actor_id": "apify/some-invented-actor",
            "actor_input": {"directUrls": ["x"], "resultsLimit": 5},
            "output_shape": {"columns": ["caption"]},
            "reasoning": "nope",
        },
    )

    plan = plan_extraction(
        URL, "scrape posts", 50, INSTAGRAM_CANDIDATES, mock_anthropic_client
    )

    # Falls back to the is_default candidate (the post scraper).
    assert plan["actor_id"] == "apify/instagram-post-scraper"
    assert plan["actor_input"] == {
        "directUrls": ["https://instagram.com/natgeo"],
        "resultsLimit": 50,
    }
    assert plan["output_shape"]["columns"] == INSTAGRAM_POST["default_columns"]
    # Invalid plan -> retried once before falling back.
    assert mock_anthropic_client.messages.create.call_count == 2


def test_invalid_columns_stripped(mock_anthropic_client):
    """Columns not in all_columns are dropped; valid ones are kept in order."""
    _set_response(
        mock_anthropic_client,
        {
            "actor_id": "apify/instagram-post-scraper",
            "actor_input": {
                "directUrls": ["https://instagram.com/natgeo"],
                "resultsLimit": 10,
            },
            "output_shape": {
                "columns": ["caption", "madeUpField", "likesCount", "nope"],
                "rename": {},
            },
            "reasoning": "posts",
        },
    )

    plan = plan_extraction(
        URL, "captions and likes", 50, INSTAGRAM_CANDIDATES,
        mock_anthropic_client,
    )

    assert plan["output_shape"]["columns"] == ["caption", "likesCount"]


def test_invalid_json_retries_once_then_falls_back(mock_anthropic_client):
    """Two unparseable responses -> default plan; create called exactly twice."""
    bad = mock_anthropic_client._make_response("not json at all {{{")
    mock_anthropic_client.messages.create.side_effect = [bad, bad]

    plan = plan_extraction(
        URL, "scrape posts", 50, INSTAGRAM_CANDIDATES, mock_anthropic_client
    )

    assert plan["actor_id"] == "apify/instagram-post-scraper"  # is_default
    assert plan["output_shape"]["columns"] == INSTAGRAM_POST["default_columns"]
    assert mock_anthropic_client.messages.create.call_count == 2


def test_max_items_clamped_to_ceiling(mock_anthropic_client):
    """A planner-proposed resultsLimit above the ceiling is clamped down."""
    _set_response(
        mock_anthropic_client,
        {
            "actor_id": "apify/instagram-post-scraper",
            "actor_input": {
                "directUrls": ["https://instagram.com/natgeo"],
                "resultsLimit": 5000,
            },
            "output_shape": {"columns": ["caption"]},
            "reasoning": "lots of posts",
        },
    )

    plan = plan_extraction(
        URL, "everything", 100, INSTAGRAM_CANDIDATES, mock_anthropic_client
    )

    assert plan["actor_input"]["resultsLimit"] == 100


def test_profile_scraper_username_extracted(mock_anthropic_client):
    """Profile intent -> profile actor with the username pulled from the URL."""
    _set_response(
        mock_anthropic_client,
        {
            "actor_id": "apify/instagram-profile-scraper",
            "actor_input": {"usernames": ["natgeo"]},
            "output_shape": {"columns": ["biography", "followersCount"]},
            "reasoning": "User asked for follower count and bio.",
        },
    )

    plan = plan_extraction(
        URL, "get the follower count and bio", 50, INSTAGRAM_CANDIDATES,
        mock_anthropic_client,
    )

    assert plan["actor_id"] == "apify/instagram-profile-scraper"
    assert plan["actor_input"] == {"usernames": ["natgeo"]}
    assert plan["output_shape"]["columns"] == ["biography", "followersCount"]


# --- Decision 2 clamp covers every known limit field ------------------------

LINKEDIN_JOBS = {
    "domain_patterns": ["linkedin.com", "www.linkedin.com"],
    "actor_id": "curious_coder/linkedin-jobs-scraper",
    "intent_description": "List job postings from a LinkedIn Jobs search URL.",
    "input_template": {"urls": ["{url}"], "count": "{max_items}"},
    "input_notes": "urls is a string array; the count field caps results.",
    "row_unit": "job",
    "default_columns": ["title", "companyName"],
    "all_columns": ["title", "companyName", "location"],
    "is_default": True,
}

AMAZON = {
    "domain_patterns": ["amazon.com", "www.amazon.com"],
    "actor_id": "junglee/amazon-crawler",
    "intent_description": "Scrape Amazon products from a product/category URL.",
    "input_template": {
        "categoryOrProductUrls": [{"url": "{url}"}],
        "maxItemsPerStartUrl": "{max_items}",
    },
    "input_notes": "categoryOrProductUrls is an array of {url} objects.",
    "row_unit": "product",
    "default_columns": ["title", "brand"],
    "all_columns": ["title", "brand", "price"],
    "is_default": True,
}


@pytest.mark.parametrize(
    "candidate, limit_key, url",
    [
        (LINKEDIN_JOBS, "count", "https://www.linkedin.com/jobs/search/?keywords=python"),
        (AMAZON, "maxItemsPerStartUrl", "https://www.amazon.com/dp/B0B3BVWJ6Y"),
    ],
)
def test_new_limit_keys_clamped_to_ceiling(candidate, limit_key, url):
    """count and maxItemsPerStartUrl are clamped to the ceiling like maxItems.

    Exercises _validate_plan directly with the limit field pre-set to 10000:
    without these keys in _LIMIT_KEYS the value would survive unclamped.
    """
    actor_input = _substitute_template(candidate["input_template"], url, 10000)
    assert actor_input[limit_key] == 10000  # planted above the ceiling

    plan = {
        "actor_id": candidate["actor_id"],
        "actor_input": actor_input,
        "output_shape": {"columns": candidate["default_columns"]},
        "reasoning": "",
    }

    validated = _validate_plan(plan, [candidate], 50)

    assert validated is not None
    assert validated["actor_input"][limit_key] == 50
