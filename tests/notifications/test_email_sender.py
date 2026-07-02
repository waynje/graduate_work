from types import SimpleNamespace

from notification_service.email_sender import build_email_sender


def test_log_sender_returns_provider_message_id():
    settings = SimpleNamespace(
        notify_sender_mode="log",
        notify_default_sender_email="noreply@movies.local",
    )
    sender = build_email_sender(settings)
    result = sender.send_email(user_id="user-1", subject="Hello", body="Body")
    assert result.provider_message_id.startswith("log-")
