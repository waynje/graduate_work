from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from ugc_service.services import bookmarks, ratings, reviews
from ugc_service.services.common import NotFoundError, ServiceValidationError
from ugc_service.schemas import (
    ValidationError,
    validate_click_event,
    validate_custom_event,
    validate_page_view_event,
)


events_blueprint = Blueprint("events", __name__, url_prefix="/api/v1/events")
ugc_blueprint = Blueprint("ugc", __name__, url_prefix="/api/v1/ugc")
logger = logging.getLogger(__name__)


def _publish(validated_payload: dict):
    producer = current_app.extensions["event_producer"]
    try:
        producer.send(validated_payload)
    except Exception as exc:
        logger.exception("Failed to publish event to Kafka: %s", exc)
        return jsonify({"error": "Event pipeline is temporarily unavailable."}), 503
    return jsonify({"status": "accepted"}), 202


def _get_json_payload() -> tuple[dict | None, tuple | None]:
    payload = request.get_json(silent=True)
    if payload is None:
        return None, (jsonify({"error": "Request body must be valid JSON."}), 422)
    if not isinstance(payload, dict):
        return None, (jsonify({"error": "JSON body must be an object."}), 422)
    return payload, None


def _extract_user_id() -> tuple[str | None, tuple | None]:
    header_name = current_app.config["UGC_API_TRUSTED_USER_ID_HEADER"]
    require_user_id = current_app.config["UGC_REQUIRE_TRUSTED_USER_ID"]
    raw_user_id = request.headers.get(header_name)

    if raw_user_id is None:
        if require_user_id:
            return None, (jsonify({"error": f"Missing trusted user header: {header_name}"}), 401)
        return None, None

    user_id = raw_user_id.strip()
    if not user_id:
        return None, (jsonify({"error": f"Header {header_name} must not be empty."}), 401)
    return user_id, None


def _extract_required_user_id() -> tuple[str | None, tuple | None]:
    user_id, error = _extract_user_id()
    if error is not None:
        return None, error
    if not user_id:
        header_name = current_app.config["UGC_API_TRUSTED_USER_ID_HEADER"]
        return None, (jsonify({"error": f"Missing trusted user header: {header_name}"}), 401)
    return user_id, None


def _parse_int_query_param(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.args.get(name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


@events_blueprint.post("/click")
def track_click():
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    user_id, auth_error = _extract_user_id()
    if auth_error is not None:
        return auth_error
    try:
        payload = validate_click_event(payload_raw, user_id=user_id)
    except ValidationError as exc:
        return jsonify({"error": "Validation failed.", "details": exc.errors()}), 422
    return _publish(payload)


@events_blueprint.post("/page-view")
def track_page_view():
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    user_id, auth_error = _extract_user_id()
    if auth_error is not None:
        return auth_error
    try:
        payload = validate_page_view_event(payload_raw, user_id=user_id)
    except ValidationError as exc:
        return jsonify({"error": "Validation failed.", "details": exc.errors()}), 422
    return _publish(payload)


@events_blueprint.post("/custom")
def track_custom_event():
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    user_id, auth_error = _extract_user_id()
    if auth_error is not None:
        return auth_error
    try:
        payload = validate_custom_event(payload_raw, user_id=user_id)
    except ValidationError as exc:
        return jsonify({"error": "Validation failed.", "details": exc.errors()}), 422
    return _publish(payload)


@events_blueprint.get("/health")
def healthcheck():
    return jsonify({"status": "ok"}), 200


@ugc_blueprint.post("/movies/<movie_id>/rating")
def upsert_movie_rating(movie_id: str):
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    assert payload_raw is not None
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error
    try:
        result = ratings.upsert_movie_rating(movie_id=movie_id, user_id=user_id, score=payload_raw.get("score"))
    except ServiceValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(result), 200


@ugc_blueprint.delete("/movies/<movie_id>/rating")
def delete_movie_rating(movie_id: str):
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error

    try:
        ratings.delete_movie_rating(movie_id=movie_id, user_id=user_id)
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"status": "ok"}), 200


@ugc_blueprint.get("/movies/<movie_id>/rating/stats")
def movie_rating_stats(movie_id: str):
    return jsonify(ratings.movie_rating_stats(movie_id=movie_id)), 200


@ugc_blueprint.get("/users/<user_id>/likes")
def list_user_likes(user_id: str):
    limit = _parse_int_query_param("limit", default=100, minimum=1, maximum=1000)
    offset = _parse_int_query_param("offset", default=0, minimum=0, maximum=1_000_000)

    return jsonify(ratings.list_user_likes(user_id=user_id, limit=limit, offset=offset)), 200


@ugc_blueprint.post("/movies/<movie_id>/reviews")
def add_review(movie_id: str):
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    assert payload_raw is not None
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error

    try:
        review_id = reviews.add_review(
            movie_id=movie_id,
            user_id=user_id,
            review_text=payload_raw.get("review_text"),
            movie_score=payload_raw.get("movie_score"),
        )
    except ServiceValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify({"status": "ok", "review_id": review_id}), 201


@ugc_blueprint.post("/reviews/<review_id>/vote")
def vote_review(review_id: str):
    payload_raw, error_response = _get_json_payload()
    if error_response is not None:
        return error_response
    assert payload_raw is not None
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error

    raw_vote = payload_raw.get("vote")
    try:
        reviews.vote_review(review_id=review_id, user_id=user_id, vote_name=raw_vote)
    except ServiceValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"status": "ok", "review_id": review_id, "vote": raw_vote}), 200


@ugc_blueprint.get("/movies/<movie_id>/reviews")
def list_reviews(movie_id: str):
    sort = request.args.get("sort", "helpful_desc")
    limit = _parse_int_query_param("limit", default=20, minimum=1, maximum=100)
    offset = _parse_int_query_param("offset", default=0, minimum=0, maximum=1_000_000)

    try:
        result = reviews.list_reviews(movie_id=movie_id, sort=sort, limit=limit, offset=offset)
    except ServiceValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify(result), 200


@ugc_blueprint.post("/movies/<movie_id>/bookmarks")
def add_bookmark(movie_id: str):
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error

    bookmarks.add_bookmark(movie_id=movie_id, user_id=user_id)
    return jsonify({"status": "ok"}), 200


@ugc_blueprint.delete("/movies/<movie_id>/bookmarks")
def delete_bookmark(movie_id: str):
    user_id, auth_error = _extract_required_user_id()
    if auth_error is not None:
        return auth_error

    try:
        bookmarks.delete_bookmark(movie_id=movie_id, user_id=user_id)
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"status": "ok"}), 200


@ugc_blueprint.get("/users/<user_id>/bookmarks")
def list_bookmarks(user_id: str):
    return jsonify(bookmarks.list_bookmarks(user_id=user_id)), 200
