"""
Article deduplication using Levenshtein distance.
Groups similar articles to reduce UI clutter.
"""

import hashlib
from collections import defaultdict
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
        buckets: Dict[str, List[Dict]] = defaultdict(list)
        for article in articles:
            h = article.get('similarity_hash') or self.calculate_similarity_hash(article['title'])
            buckets[h].append(article)

        groups = []
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            # Cap per-bucket comparisons to prevent O(n²) blowup on very similar content
            if len(bucket) > 50:
                bucket = bucket[:50]
            processed: set = set()
            for i, article in enumerate(bucket):
                if i in processed:
                    continue
                group = [article]
                processed.add(i)
                for j, other in enumerate(bucket[i + 1:], start=i + 1):
                    if j in processed:
                        continue
                    dist = levenshtein_distance(
                        article['title'].lower(),
                        other['title'].lower(),
                    )
                    if dist <= self.threshold:
                        group.append(other)
                        processed.add(j)
                if len(group) > 1:
                    groups.append(group)

        return groups

    def mark_duplicates_in_db(self, db_manager, groups: List[List[Dict]]):
        hash_updates = []
        coverage_updates = []

        for group in groups:
            if not group:
                continue

            sorted_group = sorted(group, key=lambda x: x.get('published', ''))
            similarity_hash = self.calculate_similarity_hash(sorted_group[0]['title'])

            for article in sorted_group:
                hash_updates.append((similarity_hash, article['id']))
                if article.get('published'):
                    coverage_updates.append((similarity_hash, article['published']))

        if hash_updates:
            db_manager.batch_update_similarity_hashes(hash_updates)
        if coverage_updates:
            db_manager.batch_update_coverage_stats(coverage_updates)

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
