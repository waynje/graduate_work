FILM_WORK_BATCH = """
SELECT
    fw.id,
    fw.title,
    fw.description,
    fw.creation_date,
    fw.rating AS imdb_rating,
    fw.type,
    fw.created,
    fw.modified AS updated_at
FROM content.film_work fw
WHERE fw.modified > %(updated_after)s
ORDER BY fw.modified
LIMIT %(batch_size)s;
"""

GENRES_BY_FILM_IDS = """
SELECT
    gfw.film_work_id,
    g.id AS genre_id,
    g.name AS genre_name
FROM content.genre_film_work gfw
JOIN content.genre g ON g.id = gfw.genre_id
WHERE gfw.film_work_id = ANY(%(film_work_ids)s::uuid[]);
"""

PERSONS_BY_FILM_IDS = """
SELECT
    pfw.film_work_id,
    p.id AS person_id,
    p.full_name AS person_name,
    pfw.role
FROM content.person_film_work pfw
JOIN content.person p ON p.id = pfw.person_id
WHERE pfw.film_work_id = ANY(%(film_work_ids)s::uuid[]);
"""
