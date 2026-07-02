from http import HTTPStatus
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.jwt_bearer import get_jwt_bearer
from services.film import FilmService, get_film_service
from models.film import Film as FilmDetail

router = APIRouter()


class FilmShort(BaseModel):
    id: str = Field(description="Film id")
    title: str = Field(description="Film title")
    imdb_rating: Optional[float] = Field(default=None, description="IMDB rating (if present)")

class PaginationParams:
    def __init__(
        self,
        page_number: int = Query(
            default=1,
            ge=1,
            alias="page[number]",
            description="Page number (1-based)",
        ),
        page_size: int = Query(
            default=50,
            ge=1,
            le=500,
            alias="page[size]",
            description="Page size",
        ),
    ):
        self.page_number = page_number
        self.page_size = page_size


@router.get(
    "/",
    response_model=List[FilmShort],
    summary="Films list",
    description="Return films list. Optionally filter by `genre` and sort by `sort`.",
)
async def films_list(
    _: Annotated[dict, Depends(get_jwt_bearer)],
    film_service: FilmService = Depends(get_film_service),
    genre: Optional[UUID] = Query(default=None, alias="genre"),
    sort: Optional[str] = Query(
        default=None,
        alias="sort",
        description="Sort field. Prefix with `-` for desc or `+` for asc. Example: `-imdb_rating`",
    ),
    pagination: PaginationParams = Depends(PaginationParams),
) -> List[FilmShort]:
    films = await film_service.search(
        genre=str(genre) if genre else None,
        sort=sort,
        page_number=pagination.page_number,
        page_size=pagination.page_size,
    )
    return [FilmShort(id=f.id, title=f.title, imdb_rating=f.imdb_rating) for f in films]


@router.get(
    "/search/",
    response_model=List[FilmShort],
    summary="Search films",
    description="Search films by text query in `title` and `description` (Elasticsearch full-text search).",
)
async def films_search(
    _: Annotated[dict, Depends(get_jwt_bearer)],
    film_service: FilmService = Depends(get_film_service),
    query: str = Query(..., alias="query", min_length=1, description="Text to search in title/description"),
    pagination: PaginationParams = Depends(PaginationParams),
) -> List[FilmShort]:
    films = await film_service.search(
        query=query,
        page_number=pagination.page_number,
        page_size=pagination.page_size,
    )
    return [FilmShort(id=f.id, title=f.title, imdb_rating=f.imdb_rating) for f in films]


@router.get(
    '/{film_id}/',
    response_model=FilmDetail,
    summary="Film details",
    description="Return full film details by id.",
)
async def film_details(
    film_id: UUID,
    _: Annotated[dict, Depends(get_jwt_bearer)],
    film_service: FilmService = Depends(get_film_service),
) -> FilmDetail:
    film = await film_service.get_by_id(str(film_id))
    if not film:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='film not found')

    return film