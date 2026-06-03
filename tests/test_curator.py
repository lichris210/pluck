"""Tests for curation.curate, focused on column projection.

Covers the new `keep_columns` override alongside the unchanged default
(noise/fill-rate heuristic) behavior. Dedupe and capping are exercised only
to confirm they still apply when `keep_columns` is set.
"""

from pluck.curation.curator import curate


def _rows():
    return [
        {
            "title": "Engineer",
            "companyName": "Acme",
            "location": "NYC",
            "trackingId": "a1",
            "salaryInsights": "",
        },
        {
            "title": "Designer",
            "companyName": "Globex",
            "location": "SF",
            "trackingId": "b2",
            "salaryInsights": "",
        },
    ]


# ── keep_columns: explicit projection ────────────────────────────────────────


def test_keep_columns_projects_to_exactly_those_columns():
    rows, stats = curate(_rows(), keep_columns=["title", "location"])

    assert [set(r.keys()) for r in rows] == [{"title", "location"}, {"title", "location"}]
    assert rows[0] == {"title": "Engineer", "location": "NYC"}
    # Everything not requested is reported as dropped.
    assert set(stats.dropped_columns) == {"companyName", "trackingId", "salaryInsights"}
    assert stats.columns_out == 2


def test_keep_columns_preserves_original_column_order():
    # keep_columns given out of data order; output follows the data's order.
    rows, _ = curate(_rows(), keep_columns=["location", "title"])

    assert list(rows[0].keys()) == ["title", "location"]


def test_keep_columns_keeps_noise_and_low_fill_columns_when_requested():
    # trackingId/salaryInsights would be dropped by the heuristic, but an
    # explicit keep_columns must override that.
    rows, _ = curate(_rows(), keep_columns=["title", "trackingId", "salaryInsights"])

    assert list(rows[0].keys()) == ["title", "trackingId", "salaryInsights"]


def test_keep_columns_ignores_nonexistent_columns():
    rows, _ = curate(_rows(), keep_columns=["title", "does_not_exist"])

    assert rows[0] == {"title": "Engineer"}


def test_keep_columns_overrides_heuristic_even_when_structured():
    rows, _ = curate(_rows(), is_structured=True, keep_columns=["title"])

    assert rows[0] == {"title": "Engineer"}


def test_keep_columns_applies_after_dedupe_and_before_cap():
    dupes = [
        {"title": "Engineer", "companyName": "Acme", "location": "NYC"},
        {"title": "Engineer", "companyName": "Acme", "location": "Boston"},
        {"title": "Designer", "companyName": "Globex", "location": "SF"},
    ]
    rows, stats = curate(dupes, keep_columns=["title", "location"], max_items=1)

    # Dedupe collapsed the two Engineer rows (locations merged) before the cap.
    assert stats.rows_after_dedupe == 2
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"title", "location"}
    assert rows[0]["location"] == "NYC, Boston"


def test_empty_keep_columns_falls_back_to_default_behavior():
    # Empty list is falsy → behaves as if keep_columns were None.
    rows, _ = curate(_rows(), keep_columns=[])

    # No projection (is_structured defaults False): all columns retained.
    assert set(rows[0].keys()) == {
        "title",
        "companyName",
        "location",
        "trackingId",
        "salaryInsights",
    }


# ── keep_columns=None: existing behavior unchanged ───────────────────────────


def test_none_unstructured_keeps_all_columns():
    rows, stats = curate(_rows())

    assert set(rows[0].keys()) == {
        "title",
        "companyName",
        "location",
        "trackingId",
        "salaryInsights",
    }
    assert stats.dropped_columns == []


def test_none_structured_applies_noise_and_fill_heuristic():
    rows, stats = curate(_rows(), is_structured=True)

    # trackingId is a known-noise column; salaryInsights is both noise and 0% filled.
    assert "trackingId" not in rows[0]
    assert "salaryInsights" not in rows[0]
    assert set(rows[0].keys()) == {"title", "companyName", "location"}
    assert "trackingId" in stats.dropped_columns
    assert "salaryInsights" in stats.dropped_columns


def test_none_structured_drops_low_fill_columns():
    rows = [{"title": chr(ord("A") + i)} for i in range(15)]
    rows[0]["rare"] = "x"  # filled in 1/15 rows ≈ 6.7%, below the 10% threshold

    out, stats = curate(rows, is_structured=True)

    assert "rare" not in out[0]
    assert "rare" in stats.dropped_columns


def test_none_dedupe_and_cap_still_apply():
    dupes = [
        {"title": "Engineer", "location": "NYC"},
        {"title": "Engineer", "location": "Boston"},
        {"title": "Designer", "location": "SF"},
    ]
    rows, stats = curate(dupes, max_items=1)

    assert stats.rows_in == 3
    assert stats.rows_after_dedupe == 2
    assert len(rows) == 1
