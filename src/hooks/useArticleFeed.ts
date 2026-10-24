import { useState, useEffect, useRef, useCallback } from "react";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import * as realApi from "../api";
import { NewsArticle, Settings, SourceHealth, LLMStatus } from "../types";
import { controllerPageDelta, pageTarget, visibleArticles } from "../feedLogic";

export type FeedApi = Pick<
  typeof realApi,
  "getNews" | "refreshNews" | "getSourceHealth" | "getSettings" | "getSources" | "getLLMStatus" | "markArticleRead" | "deleteArticle"
>;

export function useArticleFeed(showSettings: boolean | undefined, api: FeedApi = realApi) {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sourceHealth, setSourceHealth] = useState<SourceHealth>({});
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [fadeIn, setFadeIn] = useState(true);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [readLinks, setReadLinks] = useState<Set<string>>(new Set());
  const [unreadLinks, setUnreadLinks] = useState<Set<string>>(new Set());
  const [dismissedLinks, setDismissedLinks] = useState<Set<string>>(new Set());
  const [pendingDismiss, setPendingDismiss] = useState<string | null>(null);
  const undoTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [activeSource, setActiveSource] = useState<string>("All");
  const [newArticleCount, setNewArticleCount] = useState(0);

  const pageRef = useRef(page);
  const totalPagesRef = useRef(totalPages);
  const loadingRef = useRef(loading);
  pageRef.current = page;
  totalPagesRef.current = totalPages;
  loadingRef.current = loading;

  const loadNews = async (pageNum: number, withTransition: boolean = false) => {
    // Fade out if transition requested
    if (withTransition && articles.length > 0) {
      setFadeIn(false);
      await new Promise(resolve => setTimeout(resolve, 250)); // Wait 0.25s for fade out
    }

    setLoading(true);
    try {
      const response = await api.getNews(pageNum, 10);
      setArticles(prev => {
        const prevLinks = new Set(prev.map(a => a.link));
        const fresh = response.articles.filter(a => !prevLinks.has(a.link));
        if (pageNum === 1 && prev.length > 0) setNewArticleCount(fresh.length);
        return response.articles;
      });
      // Read-state is authoritative from the DB (article.is_read); readLinks only holds
      // this session's optimistic clicks not yet reflected by a refetch.
      setPage(response.page);
      setTotalPages(response.totalPages);

      setSourceHealth(await api.getSourceHealth());
      setLlmStatus(await api.getLLMStatus());

      if (withTransition) {
        setFadeIn(true);
      }
    } catch (error) {
      console.error("Failed to load news:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadNewsRef = useRef(loadNews);
  loadNewsRef.current = loadNews;

  const handlePageChange = useCallback((delta: number) => {
    const target = pageTarget(pageRef.current, totalPagesRef.current, loadingRef.current, delta);
    if (target !== null) loadNewsRef.current(target, true);
  }, []);

  const handleMarkRead = useCallback((link: string) => {
    setReadLinks(prev => { const s = new Set(prev); s.add(link); return s; });
    setUnreadLinks(prev => { const s = new Set(prev); s.delete(link); return s; });
    api.markArticleRead(link);
  }, []);

  const handleMarkUnread = useCallback((link: string) => {
    setUnreadLinks(prev => { const s = new Set(prev); s.add(link); return s; });
    setReadLinks(prev => { const s = new Set(prev); s.delete(link); return s; });
    api.markArticleRead(link, false);
  }, []);

  const handleDismiss = useCallback((link: string) => {
    setDismissedLinks(prev => { const s = new Set(prev); s.add(link); return s; });
    setPendingDismiss(link);
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    undoTimerRef.current = setTimeout(() => {
      api.deleteArticle(link);
      setPendingDismiss(null);
    }, 3000);
  }, []);

  const handleUndoDismiss = useCallback(() => {
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    setPendingDismiss(prev => {
      if (prev) setDismissedLinks(d => { const s = new Set(d); s.delete(prev); return s; });
      return null;
    });
  }, []);

  const handlePrevPage = useCallback(() => {
    const target = pageTarget(pageRef.current, totalPagesRef.current, loadingRef.current, -1);
    if (target !== null) {
      setActiveSource("All");
      loadNewsRef.current(target, true);
    }
  }, []);

  const handleNextPage = useCallback(() => {
    const target = pageTarget(pageRef.current, totalPagesRef.current, loadingRef.current, 1);
    if (target !== null) {
      setActiveSource("All");
      loadNewsRef.current(target, true);
    }
  }, []);

  useEffect(() => {
    api.getSettings().then(s => setSettings(s));
    api.getSources().then(setSources);
  }, []);

  useEffect(() => {
    if (!showSettings) {
      loadNews(1);
    }
  }, [showSettings]);

  useEffect(() => {
    const input = window.SteamClient?.Input;
    if (typeof input?.RegisterForControllerStateChanges !== 'function') return;
    let prevButtons = 0;
    const reg = input.RegisterForControllerStateChanges(
      (changes: Array<{ ulButtons: number }>) => {
        for (const change of changes) {
          const curr = change.ulButtons;
          const pressed = curr & ~prevButtons;
          prevButtons = curr;
          const delta = controllerPageDelta(pressed, pageRef.current, totalPagesRef.current, loadingRef.current);
          if (delta !== 0) loadNewsRef.current(pageRef.current + delta, true);
        }
      }
    );
    return () => reg?.unregister();
  }, []);

  useEffect(() => {
    const listener = addEventListener<[data: { timestamp: string }]>(
      "news_refreshed",
      (_data) => loadNewsRef.current(pageRef.current)
    );
    return () => removeEventListener("news_refreshed", listener);
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const success = await api.refreshNews();
      if (success) {
        const response = await api.getNews(page, 10);
        setArticles(response.articles);
        setPage(response.page);
        setTotalPages(response.totalPages);

        const current = await api.getSettings();
        toaster.toast({
          title: "News Refreshed",
          body: `Loaded ${response.total} articles from ${current?.sourcesEnabled?.length || 6} sources`,
        });

        setSourceHealth(await api.getSourceHealth());
      }
    } catch (error) {
      console.error("Failed to refresh:", error);
    } finally {
      setRefreshing(false);
    }
  };

  return {
    articles, visible: visibleArticles(articles, dismissedLinks, readLinks, activeSource, unreadLinks),
    page, totalPages, loading, refreshing, sourceHealth, llmStatus, fadeIn, settings, sources,
    pendingDismiss, activeSource, setActiveSource, newArticleCount,
    handlePageChange, handleMarkRead, handleMarkUnread, handleDismiss, handleUndoDismiss, handlePrevPage, handleNextPage, handleRefresh,
  };
}
