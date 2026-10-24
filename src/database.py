import functools
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any

from src.sqlite_writer import SqliteWriter


def _queued(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return self._writer.submit(lambda: method(self, *args, **kwargs))
    return wrapper


class DatabaseManager:

    SCHEMA_VERSION = 3

    def __init__(self, runtime_dir: str):
        self.db_path = Path(runtime_dir) / "deckynews.db"
        self._writer = SqliteWriter(
            self.db_path,
            pragmas=("PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL"),
            name="DBWriteWorker",
        )
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        return self._writer.connection()

    _REQUIRED_ARTICLE_COLUMNS = {"image_url", "favicon_url", "similarity_hash", "is_read"}

    _CREATE_STATEMENTS = (
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            published TEXT NOT NULL,
            source TEXT NOT NULL,
            content TEXT,
            image_url TEXT,
            favicon_url TEXT,
            similarity_hash TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_published ON articles(published DESC)",
        "CREATE INDEX IF NOT EXISTS idx_source ON articles(source)",
        "CREATE INDEX IF NOT EXISTS idx_link ON articles(link)",
        "CREATE INDEX IF NOT EXISTS idx_similarity_hash ON articles(similarity_hash)",
        "CREATE INDEX IF NOT EXISTS idx_source_published ON articles(source, published DESC)",
        "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        """
        CREATE TABLE IF NOT EXISTS article_coverage (
            similarity_hash TEXT NOT NULL,
            hour_bucket TEXT NOT NULL,
            article_count INTEGER DEFAULT 0,
            PRIMARY KEY (similarity_hash, hour_bucket)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_coverage_hash ON article_coverage(similarity_hash)",
    )

    def _init_database(self):
        conn = self._get_connection()

        pre_existing = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='articles'"
        ).fetchone() is not None

        with conn:
            for stmt in self._CREATE_STATEMENTS:
                conn.execute(stmt)
            if pre_existing:
                self._migrate_existing(conn)
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

        self._assert_schema_complete(conn)

    def _migrate_existing(self, conn: sqlite3.Connection):
        row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        version = int(row[0]) if row else 1
        columns = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}

        if version < 2:
            if "image_url" not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN image_url TEXT")
            if "favicon_url" not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN favicon_url TEXT")
        if version < 3:
            if "is_read" not in columns:
                conn.execute("ALTER TABLE articles ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0")

    def _assert_schema_complete(self, conn: sqlite3.Connection):
        columns = {r[1] for r in conn.execute("PRAGMA table_info(articles)")}
        missing = self._REQUIRED_ARTICLE_COLUMNS - columns
        if missing:
            raise RuntimeError(f"articles table missing columns after init: {sorted(missing)}")
        row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        if not row or int(row[0]) != self.SCHEMA_VERSION:
            raise RuntimeError(f"schema_version is {row and row[0]!r}, expected {self.SCHEMA_VERSION}")

    @_queued
    def insert_articles(self, articles: List[Dict]) -> Dict[str, int]:
        conn = self._get_connection()
        cursor = conn.cursor()

        rows = [
            (
                a['title'],
                a['link'],
                a['published'],
                a['source'],
                a.get('content', ''),
                a.get('image_url'),
                a.get('favicon_url'),
            )
            for a in articles
        ]

        cursor.executemany("""
            INSERT OR IGNORE INTO articles (title, link, published, source, content, image_url, favicon_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)

        conn.commit()

        inserted = cursor.rowcount

        return {
            'inserted': inserted,
            'duplicates': len(articles) - inserted,
        }

    def get_excerpt(self, link: str) -> str:
        row = self._get_connection().execute("SELECT content FROM articles WHERE link = ?", (link,)).fetchone()
        return (row["content"] or "") if row else ""

    def get_articles(
        self,
        page: int = 1,
        items_per_page: int = 10,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()

        where_clause = ""
        params: List[Any] = []

        if sources:
            placeholders = ','.join('?' * len(sources))
            where_clause = f"WHERE source IN ({placeholders})"
            params.extend(sources)

        offset = (page - 1) * items_per_page
        query = f"""
            SELECT id, title, link, published, source, similarity_hash, image_url, favicon_url, content, is_read,
                   COUNT(*) OVER() AS total_count
            FROM articles
            {where_clause}
            ORDER BY published DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [items_per_page, offset])
        rows = cursor.fetchall()

        if rows:
            total_articles = rows[0]['total_count']
            articles = [{k: v for k, v in dict(r).items() if k != 'total_count'} for r in rows]
        else:
            total_articles = 0
            articles = []

        total_pages = (total_articles + items_per_page - 1) // items_per_page

        return {
            'articles': articles,
            'total_articles': total_articles,
            'total_pages': total_pages,
            'current_page': page,
        }

    @_queued
    def mark_read(self, link: str, read: bool = True) -> bool:
        conn = self._get_connection()
        conn.execute("UPDATE articles SET is_read=? WHERE link=?", (int(read), link))
        conn.commit()
        return True

    @_queued
    def delete_by_link(self, link: str) -> bool:
        conn = self._get_connection()
        conn.execute("DELETE FROM articles WHERE link=?", (link,))
        conn.commit()
        return True

    @_queued
    def vacuum_old_articles(self) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()


        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cursor.execute("DELETE FROM articles WHERE published < ?", (cutoff_date,))
        deleted_count = cursor.rowcount
        conn.commit()


        cursor.execute("SELECT value FROM metadata WHERE key = 'last_vacuum_date'")
        row = cursor.fetchone()

        last_vacuum = None
        if row:
            last_vacuum = datetime.fromisoformat(row[0])

        should_vacuum = (
            last_vacuum is None or
            datetime.now(timezone.utc) - last_vacuum > timedelta(days=7)
        )

        if should_vacuum:
            try:
                cursor.execute("VACUUM")
            except sqlite3.OperationalError:
                logging.getLogger("DatabaseManager").warning("VACUUM failed (db busy); retry next week")
                should_vacuum = False

            if should_vacuum:
                now = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_vacuum_date', ?)",
                    (now,)
                )
                conn.commit()
                last_vacuum = datetime.now(timezone.utc)

        return {
            'deleted_count': deleted_count,
            'vacuumed': should_vacuum,
            'last_vacuum_date': last_vacuum.isoformat() if last_vacuum else None
        }

    def get_all_articles_for_deduplication(self, max_articles: int = 500) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, link, published, source, similarity_hash
            FROM articles
            ORDER BY published DESC
            LIMIT ?
        """, (max_articles,))

        return [dict(row) for row in cursor.fetchall()]

    @_queued
    def batch_update_similarity_hashes(self, updates: List[tuple]) -> None:
        conn = self._get_connection()
        conn.cursor().executemany(
            "UPDATE articles SET similarity_hash = ? WHERE id = ?",
            updates,
        )
        conn.commit()

    @_queued
    def batch_update_coverage_stats(self, updates: List[tuple]) -> None:
        from collections import Counter
        counts: Counter = Counter()
        for similarity_hash, published_time in updates:
            dt = datetime.fromisoformat(published_time.replace('Z', '+00:00'))
            bucket = dt.replace(minute=0, second=0, microsecond=0).isoformat()
            counts[(similarity_hash, bucket)] += 1

        conn = self._get_connection()
        conn.cursor().executemany("""
            INSERT INTO article_coverage (similarity_hash, hour_bucket, article_count)
            VALUES (?, ?, ?)
            ON CONFLICT(similarity_hash, hour_bucket)
            DO UPDATE SET article_count = article_count + excluded.article_count
        """, [(h, b, c) for (h, b), c in counts.items()])
        conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        conn = self._get_connection()
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @_queued
    def set_metadata(self, key: str, value: str) -> None:
        conn = self._get_connection()
        conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_coverage_sparkline(self, similarity_hash: str) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()

        cursor.execute("""
            SELECT hour_bucket, article_count
            FROM article_coverage
            WHERE similarity_hash = ?
            AND hour_bucket >= ?
            ORDER BY hour_bucket ASC
        """, (similarity_hash, cutoff))

        rows = cursor.fetchall()

        if not rows:
            return {'points': [], 'max_count': 0}

        max_count = max(row[1] for row in rows)
        points = [
            {
                'hour': row[0],
                'count': row[1],
                'normalized': int((row[1] / max_count) * 100) if max_count > 0 else 0
            }
            for row in rows
        ]

        return {'points': points, 'max_count': max_count}

    def get_similarity_hash_by_url(self, url: str) -> Optional[str]:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT similarity_hash FROM articles WHERE link = ? LIMIT 1",
            (url,)
        )
        row = cursor.fetchone()
        return row['similarity_hash'] if row and row['similarity_hash'] else None

    def count_articles_by_similarity_hash(self, similarity_hash: str) -> int:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM articles WHERE similarity_hash = ?",
            (similarity_hash,)
        )
        row = cursor.fetchone()
        return row['count'] if row else 0

    def close(self):
        self._writer.close()
