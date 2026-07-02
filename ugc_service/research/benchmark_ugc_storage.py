from __future__ import annotations

import argparse
import random
import statistics
import time
from dataclasses import dataclass

from sqlalchemy import case, func, select

from ugc_service.config import get_settings
from ugc_service.db import init_engine, session_scope
from ugc_service.models import MovieRating, UserBookmark


@dataclass
class Stats:
    avg_ms: float
    p95_ms: float
    max_ms: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure read/write latency for UGC storage.")
    parser.add_argument(
        "--iterations", type=int, default=300, help="Iterations per benchmark scenario."
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional output markdown file path for benchmark results.",
    )
    parser.add_argument("--seed", type=int, default=7, help="Deterministic random seed.")
    return parser.parse_args()


def summarize(samples_ms: list[float]) -> Stats:
    ordered = sorted(samples_ms)
    p95_index = max(0, int(len(ordered) * 0.95) - 1)
    return Stats(
        avg_ms=statistics.fmean(ordered),
        p95_ms=ordered[p95_index],
        max_ms=ordered[-1],
    )


def _movie_and_user_samples(limit: int = 2000) -> tuple[list[str], list[str]]:
    with session_scope() as session:
        movie_ids = [
            row[0]
            for row in session.execute(select(MovieRating.movie_id).distinct().limit(limit)).all()
        ]
        user_ids = [
            row[0]
            for row in session.execute(select(MovieRating.user_id).distinct().limit(limit)).all()
        ]
    if not movie_ids or not user_ids:
        raise RuntimeError("Not enough data for benchmark. Run generate_ugc_data.py first.")
    return movie_ids, user_ids


def benchmark_user_likes(iterations: int, user_ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(iterations):
        user_id = random.choice(user_ids)
        start = time.perf_counter()
        with session_scope() as session:
            session.execute(
                select(MovieRating.movie_id)
                .where(MovieRating.user_id == user_id, MovieRating.score == 10)
                .order_by(MovieRating.updated_at.desc())
                .limit(200)
            ).all()
        samples.append((time.perf_counter() - start) * 1000)
    return summarize(samples)


def benchmark_movie_like_dislike_counts(iterations: int, movie_ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(iterations):
        movie_id = random.choice(movie_ids)
        start = time.perf_counter()
        with session_scope() as session:
            session.execute(
                select(
                    func.sum(case((MovieRating.score == 10, 1), else_=0)).label("likes_count"),
                    func.sum(case((MovieRating.score == 0, 1), else_=0)).label("dislikes_count"),
                ).where(MovieRating.movie_id == movie_id)
            ).one()
        samples.append((time.perf_counter() - start) * 1000)
    return summarize(samples)


def benchmark_user_bookmarks(iterations: int, user_ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(iterations):
        user_id = random.choice(user_ids)
        start = time.perf_counter()
        with session_scope() as session:
            session.execute(
                select(UserBookmark.movie_id)
                .where(UserBookmark.user_id == user_id)
                .order_by(UserBookmark.created_at.desc())
                .limit(200)
            ).all()
        samples.append((time.perf_counter() - start) * 1000)
    return summarize(samples)


def benchmark_movie_avg_score(iterations: int, movie_ids: list[str]) -> Stats:
    samples: list[float] = []
    for _ in range(iterations):
        movie_id = random.choice(movie_ids)
        start = time.perf_counter()
        with session_scope() as session:
            session.execute(
                select(func.avg(MovieRating.score)).where(MovieRating.movie_id == movie_id)
            ).one()
        samples.append((time.perf_counter() - start) * 1000)
    return summarize(samples)


def benchmark_realtime_update_visibility(
    iterations: int, movie_ids: list[str], user_ids: list[str]
) -> Stats:
    samples: list[float] = []
    for _ in range(iterations):
        movie_id = random.choice(movie_ids)
        user_id = random.choice(user_ids)
        score = random.choice([0, 10, random.randint(1, 9)])
        start = time.perf_counter()
        with session_scope() as session:
            row = session.scalar(
                select(MovieRating).where(
                    MovieRating.user_id == user_id,
                    MovieRating.movie_id == movie_id,
                )
            )
            if row is None:
                row = MovieRating(user_id=user_id, movie_id=movie_id, score=score)
                session.add(row)
            else:
                row.score = score
        with session_scope() as session:
            session.execute(
                select(
                    func.sum(case((MovieRating.score == 10, 1), else_=0)).label("likes_count"),
                    func.sum(case((MovieRating.score == 0, 1), else_=0)).label("dislikes_count"),
                ).where(MovieRating.movie_id == movie_id)
            ).one()
        samples.append((time.perf_counter() - start) * 1000)
    return summarize(samples)


def render_report(results: dict[str, Stats]) -> str:
    database_url = get_settings().ugc_database_url
    lines = [
        "# UGC Storage Benchmark Results",
        "",
        f"Environment: `{database_url}`, SQLAlchemy ORM, synthetic dataset.",
        "",
    ]
    for scenario, stats in results.items():
        lines.extend(
            [
                f"## {scenario}",
                f"- avg: {stats.avg_ms:.2f} ms",
                f"- p95: {stats.p95_ms:.2f} ms",
                f"- max: {stats.max_ms:.2f} ms",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    init_engine(get_settings().ugc_database_url)
    movie_ids, user_ids = _movie_and_user_samples()

    results = {
        "Read: user likes list": benchmark_user_likes(args.iterations, user_ids),
        "Read: likes/dislikes count by movie": benchmark_movie_like_dislike_counts(
            args.iterations, movie_ids
        ),
        "Read: user bookmarks list": benchmark_user_bookmarks(args.iterations, user_ids),
        "Read: movie average rating": benchmark_movie_avg_score(args.iterations, movie_ids),
        "Realtime: rating update -> visible in aggregate": benchmark_realtime_update_visibility(
            args.iterations,
            movie_ids,
            user_ids,
        ),
    }

    report = render_report(results)
    print(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(report)
        print(f"Saved report to {args.output}")


if __name__ == "__main__":
    main()
