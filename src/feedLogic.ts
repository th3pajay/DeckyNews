import { NewsArticle } from "./types";

export function visibleArticles(
  articles: NewsArticle[],
  dismissed: Set<string>,
  read: Set<string>,
  activeSource: string,
  unread: Set<string> = new Set(),
): NewsArticle[] {
  return articles
    .filter(a => !dismissed.has(a.link))
    .map(a => ({ ...a, is_read: !unread.has(a.link) && (read.has(a.link) || !!a.is_read) }))
    .filter(a => activeSource === "All" || a.source === activeSource);
}

export function pageTarget(page: number, totalPages: number, loading: boolean, delta: number): number | null {
  if (loading) return null;
  if (delta < 0 && page > 1) return page - 1;
  if (delta > 0 && page < totalPages) return page + 1;
  return null;
}

export const BUTTON_PREV = 2;
export const BUTTON_NEXT = 1;

export function controllerPageDelta(pressed: number, page: number, totalPages: number, loading: boolean): number {
  if ((pressed & BUTTON_PREV) && pageTarget(page, totalPages, loading, -1) !== null) return -1;
  if ((pressed & BUTTON_NEXT) && pageTarget(page, totalPages, loading, 1) !== null) return 1;
  return 0;
}

export const PULL_MAX = 120;
export const PULL_REFRESH_AT = 80;

export function pullStage(distance: number): number {
  if (distance <= 10) return 0;
  if (distance < 40) return 1;
  if (distance < PULL_REFRESH_AT) return 2;
  return 3;
}

export function pullText(stage: number, refreshing: boolean): string {
  if (refreshing) return "Refreshing news...";
  switch (stage) {
    case 1: return "Pull down to refresh";
    case 2: return "Keep pulling...";
    case 3: return "Release to refresh!";
    default: return "";
  }
}

export function pullDistance(scrollTop: number, startY: number, currentY: number): number | null {
  if (scrollTop > 5) return null;
  const distance = currentY - startY;
  if (distance <= 0 || distance >= PULL_MAX) return null;
  return distance;
}

export function shouldRefreshOnRelease(distance: number, refreshing: boolean): boolean {
  return distance > PULL_REFRESH_AT && !refreshing;
}
