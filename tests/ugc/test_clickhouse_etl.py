from ugc_etl.transform import to_clickhouse_row


def test_to_clickhouse_row_transforms_page_view():
    row = to_clickhouse_row(
        {
            "event_id": "0f0f0f0f-0000-0000-0000-000000000001",
            "event_type": "page_view",
            "event_name": "page_view",
            "session_id": "session-1",
            "user_id": "user-1",
            "page_url": "/movies/1",
            "duration_ms": 1234,
            "referrer": "/main",
            "occurred_at": "2026-05-25T00:00:00Z",
            "ingested_at": "2026-05-25T00:00:01Z",
        }
    )

    assert row is not None
    assert row[0] == "0f0f0f0f-0000-0000-0000-000000000001"
    assert row[1] == "session-1"
    assert row[3] == "/movies/1"
    assert row[4] == 1234


def test_to_clickhouse_row_skips_non_page_view_event():
    row = to_clickhouse_row(
        {
            "event_type": "click",
            "session_id": "session-1",
            "page_url": "/movies/1",
            "duration_ms": 100,
        }
    )
    assert row is None


def test_to_clickhouse_row_skips_invalid_duration():
    row = to_clickhouse_row(
        {
            "event_type": "page_view",
            "session_id": "session-1",
            "page_url": "/movies/1",
            "duration_ms": -1,
        }
    )
    assert row is None


def test_to_clickhouse_row_skips_invalid_occurred_at():
    row = to_clickhouse_row(
        {
            "event_type": "page_view",
            "session_id": "session-1",
            "page_url": "/movies/1",
            "duration_ms": 120,
            "occurred_at": "not-a-datetime",
        }
    )
    assert row is None
