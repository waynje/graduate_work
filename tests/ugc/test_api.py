def test_click_event_is_accepted(client, fake_producer):
    response = client.post(
        "/api/v1/events/click",
        json={
            "session_id": "session-1",
            "page_url": "/movies/1",
            "element": "play_button",
            "metadata": {"source": "hero_banner"},
        },
        headers={"X-User-Id": "user-1"},
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == "accepted"
    assert len(fake_producer.messages) == 1
    assert fake_producer.messages[0]["event_type"] == "click"
    assert fake_producer.messages[0]["user_id"] == "user-1"


def test_page_view_requires_non_negative_duration(client):
    response = client.post(
        "/api/v1/events/page-view",
        json={
            "session_id": "session-2",
            "page_url": "/movies/2",
            "duration_ms": -1,
        },
        headers={"X-User-Id": "user-2"},
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "Validation failed."


def test_custom_event_rejects_unknown_event_name(client):
    response = client.post(
        "/api/v1/events/custom",
        json={
            "session_id": "session-3",
            "event_name": "unknown_event",
            "attributes": {"quality": "1080p"},
        },
        headers={"X-User-Id": "user-3"},
    )

    assert response.status_code == 422
    details = response.get_json()["details"]
    assert any("event_name" in ".".join(map(str, detail.get("loc", ()))) for detail in details)


def test_upsert_movie_rating_and_get_stats(client):
    response = client.post(
        "/api/v1/ugc/movies/movie-1/rating",
        json={"score": 10},
        headers={"X-User-Id": "user-1"},
    )
    assert response.status_code == 200

    stats_response = client.get("/api/v1/ugc/movies/movie-1/rating/stats")
    assert stats_response.status_code == 200
    body = stats_response.get_json()
    assert body["likes_count"] == 1
    assert body["dislikes_count"] == 0
    assert body["ratings_count"] == 1
    assert body["avg_score"] == 10.0


def test_add_review_and_like_vote(client):
    create_review_response = client.post(
        "/api/v1/ugc/movies/movie-2/reviews",
        json={"review_text": "Great movie", "movie_score": 9},
        headers={"X-User-Id": "author-1"},
    )
    assert create_review_response.status_code == 201
    review_id = create_review_response.get_json()["review_id"]

    vote_response = client.post(
        f"/api/v1/ugc/reviews/{review_id}/vote",
        json={"vote": "like"},
        headers={"X-User-Id": "reader-1"},
    )
    assert vote_response.status_code == 200

    list_response = client.get("/api/v1/ugc/movies/movie-2/reviews?sort=helpful_desc")
    assert list_response.status_code == 200
    items = list_response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["likes_count"] == 1
    assert items[0]["helpful_score"] == 1


def test_bookmark_lifecycle(client):
    add_response = client.post(
        "/api/v1/ugc/movies/movie-3/bookmarks",
        headers={"X-User-Id": "user-bookmarks"},
    )
    assert add_response.status_code == 200

    list_response = client.get("/api/v1/ugc/users/user-bookmarks/bookmarks")
    assert list_response.status_code == 200
    items = list_response.get_json()["items"]
    assert len(items) == 1
    assert items[0]["movie_id"] == "movie-3"

    delete_response = client.delete(
        "/api/v1/ugc/movies/movie-3/bookmarks",
        headers={"X-User-Id": "user-bookmarks"},
    )
    assert delete_response.status_code == 200
