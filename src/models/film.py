from typing import List, Optional

from pydantic import BaseModel, Field


class Person(BaseModel):
    id: str
    name: str


class Film(BaseModel):
    id: str
    title: str
    description: str = ""
    imdb_rating: Optional[float] = None
    creation_date: Optional[str] = None
    type: Optional[str] = None
    created: Optional[str] = None
    modified: Optional[str] = None

    genres: List[str] = Field(default_factory=list)
    genre_ids: List[str] = Field(default_factory=list)

    directors_names: str = ""
    actors_names: str = ""
    writers_names: str = ""

    directors: List[Person] = Field(default_factory=list)
    actors: List[Person] = Field(default_factory=list)
    writers: List[Person] = Field(default_factory=list)