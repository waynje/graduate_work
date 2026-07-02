from notification_service.personalized_email import (
    build_personalization_context,
    render_personalized_email,
)


def test_build_personalization_context_sets_defaults():
    context = build_personalization_context(user_id="user-7", payload={"movie_id": "movie-2"})
    assert context["first_name"] == "user-7"
    assert context["movie_id"] == "movie-2"
    assert "unsubscribe_url" in context


def test_render_personalized_email_substitutes_personal_fields():
    email = render_personalized_email(
        user_id="user-3",
        payload={"first_name": "Alice", "movie_id": "movie-44"},
        subject_template="Hi ${first_name}",
        body_template="Movie ${movie_id} for ${user_id}",
    )
    assert email.subject == "Hi Alice"
    assert email.body == "Movie movie-44 for user-3"
