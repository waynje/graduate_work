from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from core.queries import FILM_WORK_BATCH, GENRES_BY_FILM_IDS, PERSONS_BY_FILM_IDS


class PostgresExtractor:
    def __init__(self, conn: AsyncConnection[Any], batch_size: int) -> None:
        self.conn = conn
        self.batch_size = batch_size

    @classmethod
    async def create(cls, dsn: str, batch_size: int) -> "PostgresExtractor":
        conn = await AsyncConnection.connect(conninfo=dsn, row_factory=dict_row)
        return cls(conn=conn, batch_size=batch_size)

    async def __aenter__(self) -> "PostgresExtractor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def extract_batch(self, updated_after: str) -> Tuple[List[Dict[str, Any]], str]:
        async with self.conn.cursor() as cur:
            await cur.execute(FILM_WORK_BATCH, {"updated_after": updated_after, "batch_size": self.batch_size})
            film_rows = await cur.fetchall()

        if not film_rows:
            return [], updated_after

        film_ids = [str(r["id"]) for r in film_rows]

        genres_by_film = defaultdict(list)
        genre_ids_by_film = defaultdict(list)
        async with self.conn.cursor() as cur:
            await cur.execute(GENRES_BY_FILM_IDS, {"film_work_ids": film_ids})
            for r in await cur.fetchall():
                film_id = str(r["film_work_id"])
                genres_by_film[film_id].append(r["genre_name"])
                genre_ids_by_film[film_id].append(str(r["genre_id"]))

        persons = defaultdict(lambda: {"actors": [], "writers": [], "directors": []})
        names = defaultdict(lambda: {"actors_names": [], "writers_names": [], "directors_names": []})
        async with self.conn.cursor() as cur:
            await cur.execute(PERSONS_BY_FILM_IDS, {"film_work_ids": film_ids})
            for r in await cur.fetchall():
                film_id = str(r["film_work_id"])
                role = r["role"]
                person = {"id": str(r["person_id"]), "name": r["person_name"]}
                if role == "actor":
                    persons[film_id]["actors"].append(person)
                    names[film_id]["actors_names"].append(person["name"])
                elif role == "writer":
                    persons[film_id]["writers"].append(person)
                    names[film_id]["writers_names"].append(person["name"])
                elif role == "director":
                    persons[film_id]["directors"].append(person)
                    names[film_id]["directors_names"].append(person["name"])

        docs: List[Dict[str, Any]] = []
        for r in film_rows:
            film_id = str(r["id"])
            doc = {
                "id": film_id,
                "imdb_rating": r["imdb_rating"],
                "genres": genres_by_film.get(film_id, []),
                "genre_ids": genre_ids_by_film.get(film_id, []),
                "title": r["title"],
                "description": r.get("description") or "",
                "creation_date": r.get("creation_date").isoformat() if r.get("creation_date") else None,
                "type": r.get("type"),
                "created": r.get("created").isoformat() if r.get("created") else None,
                "modified": r.get("updated_at").isoformat() if r.get("updated_at") else None,
                "directors_names": ", ".join(names[film_id]["directors_names"]) if film_id in names else "",
                "actors_names": ", ".join(names[film_id]["actors_names"]) if film_id in names else "",
                "writers_names": ", ".join(names[film_id]["writers_names"]) if film_id in names else "",
                "directors": persons[film_id]["directors"] if film_id in persons else [],
                "actors": persons[film_id]["actors"] if film_id in persons else [],
                "writers": persons[film_id]["writers"] if film_id in persons else [],
            }
            docs.append(doc)

        new_last = str(max(r["updated_at"] for r in film_rows))
        return docs, new_last

    async def close(self) -> None:
        await self.conn.close()
