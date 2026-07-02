from ugc_service.consumer import process_event
from ugc_service.db import create_tables, init_engine, session_scope
from ugc_service.models import UGCEvent, UGCRejectedEvent


def _truncate_ugc_tables() -> None:
    with session_scope() as session:
        session.query(UGCEvent).delete()
        session.query(UGCRejectedEvent).delete()


def test_process_event_persists_row():
    init_engine("sqlite+pysqlite:///./ugc_test.db")
    create_tables()
    _truncate_ugc_tables()

    processed = process_event(
        {
            "event_type": "custom",
            "event_name": "video_completed",
            "session_id": "session-4",
            "user_id": "user-4",
            "page_url": "/movies/4",
            "occurred_at": "2026-05-25T00:00:00Z",
            "attributes": {"movie_id": "4"},
        }
    )

    assert processed is True
    with session_scope() as session:
        rows = session.query(UGCEvent).all()
    assert len(rows) == 1
    assert rows[0].event_name == "video_completed"


def test_process_event_rejects_incomplete_payload():
    init_engine("sqlite+pysqlite:///./ugc_test.db")
    create_tables()
    _truncate_ugc_tables()

    processed = process_event({"event_name": "video_completed"})

    assert processed is True
    with session_scope() as session:
        rejected_rows = session.query(UGCRejectedEvent).all()
    assert len(rejected_rows) == 1
    assert "missing required fields" in rejected_rows[0].reason
