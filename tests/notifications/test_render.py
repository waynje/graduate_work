from notification_service.render import render_template


def test_render_template_substitutes_known_keys():
    result = render_template("Hello ${user_id}, movie=${movie_id}", {"user_id": "u-1", "movie_id": "m-42"})
    assert result == "Hello u-1, movie=m-42"


def test_render_template_keeps_unknown_placeholders():
    result = render_template("Hello ${user_id}, ${unknown}", {"user_id": "u-1"})
    assert result == "Hello u-1, ${unknown}"
