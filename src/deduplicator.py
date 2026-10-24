import hashlib
from collections import defaultdict
from typing import List, Dict
from rapidfuzz import process as fuzz_process
from rapidfuzz.distance import Levenshtein as fuzz_lev


class ArticleDeduplicator:

    def __init__(self, similarity_threshold: int = 10):
        self.threshold = similarity_threshold

    def calculate_similarity_hash(self, title: str) -> str:

        normalized = title.lower()
        normalized = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in normalized)


        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        words = [w for w in normalized.split() if w and w not in stopwords]


        words = sorted(set(words))


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

            if len(bucket) > 50:
                bucket = bucket[:50]
            bucket_titles = [a['title'].lower() for a in bucket]
            matrix = fuzz_process.cdist(bucket_titles, bucket_titles, scorer=fuzz_lev.distance)
            processed: set = set()
            for i in range(len(bucket)):
                if i in processed:
                    continue
                group = [bucket[i]]
                processed.add(i)
                for j in range(i + 1, len(bucket)):
                    if j in processed:
                        continue
                    if matrix[i][j] <= self.threshold:
                        group.append(bucket[j])
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
