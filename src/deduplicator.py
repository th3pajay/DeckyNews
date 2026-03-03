"""
Article deduplication using Levenshtein distance.
Groups similar articles to reduce UI clutter.
"""

import hashlib
from typing import List, Dict, Optional
from Levenshtein import distance as levenshtein_distance


class ArticleDeduplicator:
    """
    Semantic fuzzy-matching using Levenshtein distance.

    This class identifies duplicate or near-duplicate articles across
    different sources based on title similarity. Articles within a
    configurable edit distance threshold are grouped together.

    Example:
        - "Sony Announces PS5 Pro Release Date"
        - "Sony announces PS5 Pro release date - Full details"
        - Edit distance: 18 characters

    The similarity hash provides fast pre-filtering before expensive
    distance calculations.
    """

    def __init__(self, similarity_threshold: int = 10):
        """
        Initialize deduplicator.

        Args:
            similarity_threshold: Maximum Levenshtein edit distance
                                 to consider articles as duplicates.
                                 Lower = stricter matching.
                                 Typical values: 5-15
        """
        self.threshold = similarity_threshold

    def calculate_similarity_hash(self, title: str) -> str:
        """
        Create normalized hash for fast pre-filtering.

        Normalizations applied:
        - Lowercase conversion
        - Remove punctuation
        - Remove common stopwords ("the", "a", "an")
        - Sort words alphabetically
        - Hash to 8-character hex string

        Args:
            title: Article title

        Returns:
            8-character hex hash string
        """
        # Normalize: lowercase + remove punctuation
        normalized = title.lower()
        normalized = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in normalized)

        # Remove common stopwords
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        words = [w for w in normalized.split() if w and w not in stopwords]

        # Sort words to make hash order-independent
        words = sorted(set(words))

        # Create hash
        text = ' '.join(words)
        return hashlib.md5(text.encode()).hexdigest()[:8]

    def find_duplicates(self, articles: List[Dict]) -> List[List[Dict]]:
        """
        Group articles by title similarity.

        Uses O(n²) comparison with Levenshtein distance.
        For large datasets (>1000 articles), consider limiting
        to most recent N articles.

        Args:
            articles: List of article dicts with 'title' key

        Returns:
            List of duplicate groups. Each group is a list of articles.
            Only returns groups with 2+ articles.

        Example:
            [
                [article1, article2, article3],  # Group 1: similar titles
                [article4, article5]             # Group 2: similar titles
            ]
        """
        groups = []
        processed = set()

        for i, article in enumerate(articles):
            if i in processed:
                continue

            # Start new group with current article
            group = [article]
            processed.add(i)

            # Compare with remaining articles
            for j, other in enumerate(articles[i+1:], start=i+1):
                if j in processed:
                    continue

                # Calculate edit distance
                dist = levenshtein_distance(
                    article['title'].lower(),
                    other['title'].lower()
                )

                if dist <= self.threshold:
                    group.append(other)
                    processed.add(j)

            # Only add groups with duplicates
            if len(group) > 1:
                groups.append(group)

        return groups

    def mark_duplicates_in_db(self, db_manager, groups: List[List[Dict]]):
        """
        Update articles table with similarity_hash for grouped articles.

        The "master" article (first in group, typically earliest published)
        gets the similarity_hash. Other articles in the group get the same hash,
        allowing the frontend to group them under "See X similar stories".

        Also populates coverage stats for sparkline visualization.

        Args:
            db_manager: DatabaseManager instance
            groups: List of duplicate groups from find_duplicates()
        """
        for group in groups:
            if not group:
                continue

            # Sort by published date (earliest first)
            sorted_group = sorted(
                group,
                key=lambda x: x.get('published', '')
            )

            # Master article: first (earliest)
            master = sorted_group[0]

            # Generate hash for this group
            similarity_hash = self.calculate_similarity_hash(master['title'])

            # Update all articles in group with same hash and coverage stats
            for article in sorted_group:
                db_manager.update_similarity_hash(
                    article['id'],
                    similarity_hash
                )

                # Update coverage stats for sparkline data
                if article.get('published'):
                    db_manager.update_coverage_stats(
                        similarity_hash,
                        article['published']
                    )

    def get_duplicate_stats(self, articles: List[Dict]) -> Dict[str, int]:
        """
        Get statistics about duplicates without modifying database.

        Args:
            articles: List of article dicts

        Returns:
            Dict with 'total_articles', 'duplicate_groups', 'total_duplicates'
        """
        groups = self.find_duplicates(articles)

        total_duplicates = sum(len(group) - 1 for group in groups)

        return {
            'total_articles': len(articles),
            'duplicate_groups': len(groups),
            'total_duplicates': total_duplicates
        }
