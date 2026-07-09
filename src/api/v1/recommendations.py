from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.jwt_bearer import get_jwt_bearer
from services.recommendation import get_recommendation_service
from services.recommendation_logic import RecommendationResult
from services.recommendation_service import RecommendationService

router = APIRouter()


class RecommendationItem(BaseModel):
    id: str = Field(description="Film id")
    title: str = Field(description="Film title")
    imdb_rating: Optional[float] = Field(default=None, description="IMDB rating")
    score: float = Field(description="Recommendation score")
    reason: str = Field(description="Why this film was recommended: genre_match, popular")


class ViewingHistoryItem(BaseModel):
    movie_id: str
    duration_ms: Optional[int] = None
    occurred_at: Optional[str] = None


@router.get(
    "/",
    response_model=List[RecommendationItem],
    summary="Personalized film recommendations",
    description=(
        "Return personalized recommendations based on viewing history, ratings and bookmarks. "
        "Cold-start users receive popular films."
    ),
)
async def get_recommendations(
    token_payload: Annotated[dict, Depends(get_jwt_bearer)],
    recommendation_service: RecommendationService = Depends(get_recommendation_service),
    limit: int = Query(default=20, ge=1, le=100, description="Number of recommendations"),
) -> List[RecommendationItem]:
    user_id = token_payload["sub"]
    items: list[RecommendationResult] = await recommendation_service.get_recommendations(
        user_id=user_id,
        limit=limit,
    )
    return [
        RecommendationItem(
            id=item.film.id,
            title=item.film.title,
            imdb_rating=item.film.imdb_rating,
            score=item.score,
            reason=item.reason,
        )
        for item in items
    ]


@router.get(
    "/history/",
    response_model=List[ViewingHistoryItem],
    summary="Viewing history",
    description="Return deduplicated viewing history derived from page_view UGC events.",
)
async def get_viewing_history(
    token_payload: Annotated[dict, Depends(get_jwt_bearer)],
    recommendation_service: RecommendationService = Depends(get_recommendation_service),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum history items"),
) -> List[ViewingHistoryItem]:
    user_id = token_payload["sub"]
    history = await recommendation_service.get_viewing_history(user_id=user_id, limit=limit)
    return [ViewingHistoryItem(**item) for item in history]
