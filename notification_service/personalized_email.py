from __future__ import annotations

from dataclasses import dataclass

from notification_service.render import render_template


@dataclass(frozen=True)
class PersonalizedEmail:
    subject: str
    body: str
    personalization_context: dict


def build_personalization_context(*, user_id: str, payload: dict) -> dict:
    first_name = payload.get("first_name")
    if not isinstance(first_name, str) or not first_name.strip():
        first_name = user_id
    context = {
        "user_id": user_id,
        "first_name": first_name.strip(),
        "full_name": payload.get("full_name", first_name.strip()),
        "movie_id": payload.get("movie_id", ""),
        "unsubscribe_url": payload.get("unsubscribe_url", f"https://movies.local/unsubscribe/{user_id}"),
    }
    # Allow scenario-specific keys while preserving defaults above.
    context.update(payload)
    return context


def render_personalized_email(
    *, user_id: str, payload: dict, subject_template: str, body_template: str
) -> PersonalizedEmail:
    context = build_personalization_context(user_id=user_id, payload=payload)
    subject = render_template(subject_template, context)
    body = render_template(body_template, context)
    return PersonalizedEmail(subject=subject, body=body, personalization_context=context)
