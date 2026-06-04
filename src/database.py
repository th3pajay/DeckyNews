"""
SQLite database manager for DeckyNews article storage.
Replaces JSON caching with proper relational database.
"""

import sqlite3
import threading
import re
import queue
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any, Callable


class DatabaseManager:
    """
    Thread-safe SQLite database manager for article storage.
    Uses thread-local connections and a serialized write queue to prevent lock contention.
    WAL mode enabled for crash recovery.
    """

    SCHEMA_VERSION = 2

    def __init__(self, runtime_dir: str):
        """
        Initialize database manager.

        Args:
            runtime_dir: Plugin runtime directory path
        """
        self.db_path = Path(runtime_dir) / "deckynews.db"
        self._local = threading.local()
        self._write_queue: queue.Queue = queue.Queue()
        self._write_worker_running = threading.Event()
        self._write_worker_running.set()
        self._write_worker_thread = threading.Thread(
            target=self._write_worker,
            daemon=True,
            name="DBWriteWorker"
        )
        self._write_worker_thread.start()

        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0
            )
            self._local.conn.row_factory = sqlite3.Row

            self._local.conn.execute("PRAGMA journal_mode=WAL")

            self._local.conn.execute("PRAGMA synchronous=NORMAL")

            def _regexp(pattern: str, text: str) -> bool:
                try:
                    return re.search(pattern, text, re.IGNORECASE) is not None
                except re.error:
                    return False

            self._local.conn.create_function("REGEXP", 2, _regexp)

        return self._local.conn

    def _write_worker(self):
        while self._write_worker_running.is_set():
            try:
                # Block for up to 1 second waiting for work
                write_op = self._write_queue.get(timeout=1.0)

                if write_op is None:  # Poison pill to stop worker
                    break

                # Execute the write operation
                func, args, kwargs, result_queue = write_op
                try:
                    result = func(*args, **kwargs)
                    if result_queue:
                        result_queue.put(("success", result))
                except Exception as e:
                    if result_queue:
                        result_queue.put(("error", e))

                self._write_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                import logging
                logging.warning(f"[DatabaseManager] Write worker error: {e}")

    def _queue_write(self, func: Callable, *args, **kwargs):
        """
        Queue a write operation for serial execution.

        Args:
            func: The write function to execute
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result of the write operation
        """
        result_queue: queue.Queue = queue.Queue()
        self._write_queue.put((func, args, kwargs, result_queue))

        # Wait for result (blocking)
        status, result = result_queue.get(timeout=30)
        if status == "error":
            raise result
        return result

    def _init_database(self):
        """Create database schema if not exists."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Create articles table
        cursor.execute("""
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_published
            ON articles(published DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source
            ON articles(source)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_link
            ON articles(link)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_similarity_hash
            ON articles(similarity_hash)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_published
            ON articles(source, published DESC)
        """)

        # Create metadata table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Create article_coverage table for sparklines
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS article_coverage (
                similarity_hash TEXT NOT NULL,
                hour_bucket TEXT NOT NULL,
                article_count INTEGER DEFAULT 0,
                PRIMARY KEY (similarity_hash, hour_bucket)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_coverage_hash
            ON article_coverage(similarity_hash)
        """)

        # Check current schema version for migrations
        cursor.execute("SELECT value FROM metadata WHERE key = 'schema_version'")
        current_version_row = cursor.fetchone()
        current_version = int(current_version_row[0]) if current_version_row else 1

        # Migrate from version 1 to version 2
        if current_version < 2:
            try:
                cursor.execute("ALTER TABLE articles ADD COLUMN image_url TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute("ALTER TABLE articles ADD COLUMN favicon_url TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Update schema version
            cursor.execute("""
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES ('schema_version', '2')
            """)
            conn.commit()

        # Store schema version (for new databases)
        cursor.execute("""
            INSERT OR IGNORE INTO metadata (key, value)
            VALUES ('schema_version', ?)
        """, (str(self.SCHEMA_VERSION),))

        conn.commit()

    def insert_articles(self, articles: List[Dict]) -> Dict[str, int]:
        """
        Insert articles into database with duplicate handling.

        Args:
            articles: List of article dicts with keys: title, link, published, source, image_url, favicon_url

        Returns:
            Dict with 'inserted' and 'duplicates' counts
        """
        # Queue write operation for serial execution
        return self._queue_write(self._insert_articles_impl, articles)

    def _insert_articles_impl(self, articles: List[Dict]) -> Dict[str, int]:
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

    def get_articles(
        self,
        page: int = 1,
        items_per_page: int = 10,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get paginated articles from database.

        Args:
            page: Page number (1-indexed)
            items_per_page: Number of articles per page
            sources: Optional list of source names to filter by

        Returns:
            Dict with 'articles', 'total_articles', 'total_pages', 'current_page'
        """
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
            SELECT id, title, link, published, source, similarity_hash, image_url, favicon_url, content,
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

    def search_articles(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        Search articles using regex pattern.

        Args:
            query: Regex pattern to match against title
            sources: Optional list of source names to filter by
            limit: Maximum number of results

        Returns:
            List of matching article dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Build query
        sql = "SELECT * FROM articles WHERE title REGEXP ?"
        params = [query]

        if sources:
            placeholders = ','.join('?' * len(sources))
            sql += f" AND source IN ({placeholders})"
            params.extend(sources)

        sql += " ORDER BY published DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def vacuum_old_articles(self) -> Dict[str, Any]:
        """
        Delete articles older than 30 days and run VACUUM if needed.

        VACUUM runs if:
        - Never run before, OR
        - Last run was >7 days ago

        Returns:
            Dict with 'deleted_count', 'vacuumed', 'last_vacuum_date'
        """
        # Queue write operation for serial execution
        return self._queue_write(self._vacuum_old_articles_impl)

    def _vacuum_old_articles_impl(self) -> Dict[str, Any]:
        conn = self._get_connection()
        cursor = conn.cursor()

        # Delete articles older than 30 days
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cursor.execute("DELETE FROM articles WHERE published < ?", (cutoff_date,))
        deleted_count = cursor.rowcount
        conn.commit()

        # Check when database was last vacuumed
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
                print("VACUUM failed: database busy, will retry next week")
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
        """
        Get recent articles for deduplication analysis.

        Args:
            max_articles: Maximum number of recent articles to fetch

        Returns:
            List of article dicts with id, title, link, published, source
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, link, published, source, similarity_hash
            FROM articles
            ORDER BY published DESC
            LIMIT ?
        """, (max_articles,))

        return [dict(row) for row in cursor.fetchall()]

    def update_similarity_hash(self, article_id: int, similarity_hash: str):
        """
        Update similarity_hash for an article.

        Args:
            article_id: Article ID
            similarity_hash: Computed similarity hash
        """
        # Queue write operation for serial execution
        return self._queue_write(self._update_similarity_hash_impl, article_id, similarity_hash)

    def _update_similarity_hash_impl(self, article_id: int, similarity_hash: str):
        """Internal implementation of update_similarity_hash."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE articles
            SET similarity_hash = ?
            WHERE id = ?
        """, (similarity_hash, article_id))

        conn.commit()

    def update_coverage_stats(self, similarity_hash: str, published_time: str):
        """
        Increment coverage count for a given hour bucket.
        Used for sparkline data visualization.

        Args:
            similarity_hash: The similarity hash of the article group
            published_time: ISO format timestamp of article publication
        """
        # Queue write operation for serial execution
        return self._queue_write(self._update_coverage_stats_impl, similarity_hash, published_time)

    def _update_coverage_stats_impl(self, similarity_hash: str, published_time: str):
        """Internal implementation of update_coverage_stats."""
        # Truncate to hour bucket
        dt = datetime.fromisoformat(published_time.replace('Z', '+00:00'))
        hour_bucket = dt.replace(minute=0, second=0, microsecond=0).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO article_coverage (similarity_hash, hour_bucket, article_count)
            VALUES (?, ?, 1)
            ON CONFLICT(similarity_hash, hour_bucket)
            DO UPDATE SET article_count = article_count + 1
        """, (similarity_hash, hour_bucket))

        conn.commit()

    def batch_update_similarity_hashes(self, updates: List[tuple]) -> None:
        return self._queue_write(self._batch_update_similarity_hashes_impl, updates)

    def _batch_update_similarity_hashes_impl(self, updates: List[tuple]) -> None:
        conn = self._get_connection()
        conn.cursor().executemany(
            "UPDATE articles SET similarity_hash = ? WHERE id = ?",
            updates,
        )
        conn.commit()

    def batch_update_coverage_stats(self, updates: List[tuple]) -> None:
        return self._queue_write(self._batch_update_coverage_stats_impl, updates)

    def _batch_update_coverage_stats_impl(self, updates: List[tuple]) -> None:
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

    def set_metadata(self, key: str, value: str) -> None:
        return self._queue_write(self._set_metadata_impl, key, value)

    def _set_metadata_impl(self, key: str, value: str) -> None:
        conn = self._get_connection()
        conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_coverage_sparkline(self, similarity_hash: str) -> Dict[str, Any]:
        """
        Get 24-hour coverage trend for a similarity group.

        Args:
            similarity_hash: The similarity hash to get coverage for

        Returns:
            Dict with 'points' (list of {hour, count, normalized}) and 'max_count'
        """
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
        """Close database connection (call on plugin unload)."""
        self._queue_write(lambda: self._local.conn.close() if hasattr(self._local, 'conn') else None)
        self._write_worker_running.clear()
        self._write_queue.put(None)  # Poison pill
        self._write_worker_thread.join(timeout=5.0)

        # Close connections
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
