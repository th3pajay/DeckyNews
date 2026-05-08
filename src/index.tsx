import {
  PanelSection,
  PanelSectionRow,
  staticClasses,
  Focusable,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  definePlugin,
  toaster
} from "@decky/api";
import { useState, useEffect, useRef, useCallback, FC, Component } from "react";
import { FaCog, FaSync, FaChevronLeft, FaChevronRight } from "react-icons/fa";

import { NewsArticle, Settings, SourceHealth, LLMStatus } from "./types";
import { getNews, refreshNews, getSourceHealth, getSettings, getLLMStatus } from "./api";
import { NewsItem, SkeletonArticle } from "./components/NewsItem";
import { Settings as SettingsComponent } from "./components/Settings";

declare global {
  interface Window {
    openURL?: (url: string) => boolean | void;
    SteamClient?: { Input?: { RegisterForControllerStateChanges?: (cb: (changes: Array<{ ulButtons: number }>) => void) => { unregister: () => void } } };
  }
}

const _animStyle = document.createElement('style');
_animStyle.innerHTML = `
  @keyframes shimmer { 0%,100% { opacity:0.6; } 50% { opacity:1; } }
  @keyframes blink { 0%,50% { opacity:1; } 51%,100% { opacity:0; } }
  @keyframes spin { from { transform:rotate(0deg); } to { transform:rotate(360deg); } }
  @keyframes barWave { 0%,100% { opacity:0.15; } 50% { opacity:1; } }
`;
document.head.appendChild(_animStyle);

interface DynamicBackdropProps {
  imageUrl: string | null;
  visible: boolean;
}

const DynamicBackdrop: FC<DynamicBackdropProps> = ({ imageUrl, visible }) => {
  const [currentImage, setCurrentImage] = useState<string | null>(null);

  useEffect(() => {
    if (visible && imageUrl) {
      // Preload image to avoid flicker
      const img = new Image();
      img.src = imageUrl;
      img.onload = () => setCurrentImage(imageUrl);
      return undefined;
    } else if (!visible) {
      // Delay clearing to allow fade-out
      const timeout = setTimeout(() => setCurrentImage(null), 300);
      return () => clearTimeout(timeout);
    }
    return undefined;
  }, [imageUrl, visible]);

  if (!currentImage) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: -1,
        backgroundImage: `url(${currentImage})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        filter: "blur(30px) saturate(0.5) brightness(0.3)",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s ease-in-out",
        pointerEvents: "none"
      }}
    />
  );
};

const DEFAULT_SETTINGS: Settings = {
  refreshInterval: 30,
  debugMode: false,
  sourcesEnabled: [],
  analyticsOptIn: false,
  llmEnabled: false,
  llmCooldownSeconds: 20,
  llmResourceMonitoringEnabled: true,
  uiViewMode: "comfortable",
  showSourceIcons: true,
  glassmorphismOpacity: 30,
  accentColorSource: "automatic",
  dynamicBackdropEnabled: true,
  aiTypewriterEnabled: true,
  aiTypewriterSpeed: 30,
  enableHoverPreview: true,
  hoverPreviewDelay: 500,
  aiPersonality: "analyst",
  performanceGuardEnabled: true,
  ramThresholdMB: 800,
  articleRetention: 500,
  allowLlmDuringGaming: false,
  llmTempCeilingCelsius: 75,
  llmThermalCooldownBonus: 30,
  llmAdaptiveTokens: true,
  llmReducedTokenCount: 80,
  llmAdaptiveThreads: true,
  selectedModel: "qwen2.5-0.5b",
};

function Content({ showSettings, onBackToNews }: { showSettings?: boolean; onBackToNews?: () => void }) {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sourceHealth, setSourceHealth] = useState<SourceHealth>({});
  const [pullDistance, setPullDistance] = useState(0);
  const [touchStartY, setTouchStartY] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [fadeIn, setFadeIn] = useState(true);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [backdropImage] = useState<string | null>(null);

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
      const response = await getNews(pageNum, 10);
      setArticles(response.articles);
      setPage(response.page);
      setTotalPages(response.totalPages);

      const health = await getSourceHealth();
      setSourceHealth(health);

      // Load LLM status
      const status = await getLLMStatus();
      setLlmStatus(status);

      // Fade in
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
    if (delta < 0 && pageRef.current > 1 && !loadingRef.current) loadNewsRef.current(pageRef.current - 1, true);
    else if (delta > 0 && pageRef.current < totalPagesRef.current && !loadingRef.current) loadNewsRef.current(pageRef.current + 1, true);
  }, []);

  const handlePrevPage = useCallback(() => {
    if (pageRef.current > 1 && !loadingRef.current) loadNewsRef.current(pageRef.current - 1, true);
  }, []);

  const handleNextPage = useCallback(() => {
    if (pageRef.current < totalPagesRef.current && !loadingRef.current) loadNewsRef.current(pageRef.current + 1, true);
  }, []);

  // Load settings
  useEffect(() => {
    getSettings().then(s => setSettings(s));
  }, []);

  // MUST be called before any conditional returns (React Rules of Hooks)
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
          if ((pressed & 2) && pageRef.current > 1 && !loadingRef.current) {
            loadNewsRef.current(pageRef.current - 1, true);
          } else if ((pressed & 1) && pageRef.current < totalPagesRef.current && !loadingRef.current) {
            loadNewsRef.current(pageRef.current + 1, true);
          }
        }
      }
    );
    return () => reg?.unregister();
  }, []);

  // If showing settings, render Settings component
  if (showSettings && onBackToNews) {
    return <SettingsComponent onBack={onBackToNews} />;
  }

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const success = await refreshNews();
      if (success) {
        const response = await getNews(page, 10);
        setArticles(response.articles);
        setPage(response.page);
        setTotalPages(response.totalPages);

        const settings = await getSettings();
        toaster.toast({
          title: "News Refreshed",
          body: `Loaded ${response.total} articles from ${settings?.sourcesEnabled?.length || 6} sources`,
        });

        const health = await getSourceHealth();
        setSourceHealth(health);
      }
    } catch (error) {
      console.error("Failed to refresh:", error);
    } finally {
      setRefreshing(false);
      setPullDistance(0);
    }
  };

  const handleTouchStart = (e: React.TouchEvent) => {
    setTouchStartY(e.touches[0].clientY);
    const target = e.currentTarget as HTMLElement;
    setScrollTop(target.scrollTop || 0);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (scrollTop > 5) return;

    const touchY = e.touches[0].clientY;
    const distance = touchY - touchStartY;

    if (distance > 0 && distance < 120) {
      setPullDistance(distance);
    }
  };

  const handleTouchEnd = async () => {
    if (pullDistance > 80 && !refreshing) {
      // Reset pull distance BEFORE triggering refresh to hide indicator immediately
      setPullDistance(0);
      handleRefresh();
    } else {
      setPullDistance(0);
    }
  };

  const getPullStage = (distance: number) => {
    if (distance < 40) return 1;
    if (distance < 80) return 2;
    return 3;
  };

  const getPullProgress = (distance: number) => {
    return Math.min(Math.round((distance / 80) * 100), 100);
  };

  const getPullText = (stage: number, refreshing: boolean) => {
    if (refreshing) return "Refreshing news...";
    switch (stage) {
      case 1: return "Pull down to refresh";
      case 2: return "Keep pulling...";
      case 3: return "Release to refresh!";
      default: return "";
    }
  };

  const showPullIndicator = pullDistance > 10 && !refreshing;

  return (
    <Focusable
      style={{ position: "relative" }}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      {settings?.dynamicBackdropEnabled && (
        <DynamicBackdrop
          imageUrl={backdropImage}
          visible={false}
        />
      )}
      {showPullIndicator && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
            background: "linear-gradient(to bottom, rgba(27, 40, 56, 0.95) 0%, rgba(27, 40, 56, 0) 100%)",
            transform: `translateY(${Math.min(pullDistance * 0.5, 60)}px)`,
            opacity: Math.min(pullDistance / 40, 1),
            transition: "transform 0.3s ease, opacity 0.3s ease",
          }}
        >
          <div
            style={{
              width: "40px",
              height: "40px",
              marginBottom: "8px",
              position: "relative",
            }}
          >
            <div
              style={{
                width: "40px",
                height: "40px",
                borderRadius: "50%",
                border: "3px solid rgba(26, 159, 255, 0.2)",
                borderTopColor: "#1a9fff",
                transform: `rotate(${(getPullProgress(pullDistance) / 100) * 360}deg)`,
                transition: "all 0.3s ease",
                animation: refreshing ? "spin 1s linear infinite" : "none",
              }}
            />
            {getPullStage(pullDistance) === 3 && !refreshing && (
              <span
                style={{
                  position: "absolute",
                  top: "50%",
                  left: "50%",
                  transform: "translate(-50%, -50%)",
                  fontSize: "20px",
                  color: "#1a9fff",
                }}
              >
                ✓
              </span>
            )}
          </div>
          <div
            style={{
              fontSize: "13px",
              fontWeight: 600,
              textAlign: "center",
              color: getPullStage(pullDistance) >= 2 ? "#1a9fff" : "#8b8f98",
            }}
          >
            {getPullText(getPullStage(pullDistance), refreshing)}
          </div>
          <div
            style={{
              fontSize: "11px",
              color: "#8b8f98",
              fontVariantNumeric: "tabular-nums",
              marginTop: "4px",
            }}
          >
            {getPullProgress(pullDistance)}%
          </div>
        </div>
      )}

      <PanelSection>
        <div
          style={{
            opacity: fadeIn ? 1 : 0,
            transition: "opacity 0.5s ease-in-out"
          }}
        >
          {loading && articles.length === 0 ? (
            <>
              {Array.from({ length: 10 }).map((_, i) => (
                <SkeletonArticle key={`skeleton-${i}`} />
              ))}
            </>
          ) : articles.length === 0 ? (
            <PanelSectionRow>
              <div style={{ textAlign: "center", padding: "20px", color: "#8b8f98" }}>
                No news available - try refreshing
              </div>
            </PanelSectionRow>
          ) : (
            articles.map((article, idx) => (
              <NewsItem
                key={article.link}
                article={article}
                health={sourceHealth[article.source] || 'ok'}
                llmEnabled={llmStatus?.enabled ?? false}
                llmStatus={llmStatus}
                settings={settings ?? DEFAULT_SETTINGS}
                index={idx}
                onPageChange={handlePageChange}
              />
            ))
          )}
        </div>
      </PanelSection>

      {totalPages > 1 && (
        <PanelSection>
          <PanelSectionRow>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: "12px",
                padding: "16px 0",
                borderTop: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "16px",
                }}
              >
                <Focusable
                  onActivate={handlePrevPage}
                  onClick={handlePrevPage}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "40px",
                    height: "40px",
                    borderRadius: "50%",
                    background: page === 1 ? "rgba(255, 255, 255, 0.05)" : "rgba(26, 159, 255, 0.1)",
                    border: `1px solid ${page === 1 ? "rgba(255, 255, 255, 0.1)" : "rgba(26, 159, 255, 0.3)"}`,
                    cursor: page === 1 || loading ? "not-allowed" : "pointer",
                    opacity: page === 1 || loading ? 0.5 : 1,
                    transition: "all 0.2s ease",
                  }}
                >
                  <FaChevronLeft style={{ fontSize: "16px", color: page === 1 ? "#8b8f98" : "#1a9fff" }} />
                </Focusable>
                <div
                  style={{
                    fontSize: "14px",
                    color: "#ffffff",
                    fontWeight: 500,
                    fontVariantNumeric: "tabular-nums",
                    minWidth: "80px",
                    textAlign: "center",
                  }}
                >
                  {page} / {totalPages}
                </div>
                <Focusable
                  onActivate={handleNextPage}
                  onClick={handleNextPage}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    width: "40px",
                    height: "40px",
                    borderRadius: "50%",
                    background: page === totalPages ? "rgba(255, 255, 255, 0.05)" : "rgba(26, 159, 255, 0.1)",
                    border: `1px solid ${page === totalPages ? "rgba(255, 255, 255, 0.1)" : "rgba(26, 159, 255, 0.3)"}`,
                    cursor: page === totalPages || loading ? "not-allowed" : "pointer",
                    opacity: page === totalPages || loading ? 0.5 : 1,
                    transition: "all 0.2s ease",
                  }}
                >
                  <FaChevronRight style={{ fontSize: "16px", color: page === totalPages ? "#8b8f98" : "#1a9fff" }} />
                </Focusable>
              </div>
              <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  const pageNum = i + 1;
                  const isPast = pageNum < page;
                  const isCurrent = pageNum === page;
                  return (
                    <div
                      key={pageNum}
                      style={{
                        width: isCurrent ? "10px" : "8px",
                        height: isCurrent ? "10px" : "8px",
                        borderRadius: "50%",
                        background: isCurrent
                          ? "#1a9fff"
                          : isPast
                          ? "rgba(26, 159, 255, 0.6)"
                          : "rgba(255, 255, 255, 0.2)",
                        boxShadow: isCurrent ? "0 0 8px rgba(26, 159, 255, 0.6)" : "none",
                        transition: "all 0.3s ease",
                      }}
                    />
                  );
                })}
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

    </Focusable>
  );
}

// State management for settings toggle
let setShowSettingsGlobal: ((show: boolean) => void) | null = null;

class ErrorBoundary extends Component<{ children: any }, { hasError: boolean }> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return "Something went wrong loading the news plugin.";
    }
    return this.props.children;
  }
}

function MainContent() {
  const [showSettings, setShowSettings] = useState(false);

  // Expose setter globally for title bar access
  useEffect(() => {
    setShowSettingsGlobal = setShowSettings;
    return () => { setShowSettingsGlobal = null; };
  }, []);

  return (
    <ErrorBoundary>
      <Content
        showSettings={showSettings}
        onBackToNews={() => setShowSettings(false)}
      />
    </ErrorBoundary>
  );
}

const ColoredNewsIcon: FC = () => {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M2 3h14v18H2V3zm2 2v14h10V5H4zm14-2h4v18h-4V3zm2 2v14h-0V5z"
        fill="url(#newsGradient)"
      />
      <rect x="6" y="7" width="6" height="2" fill="#1a9fff" />
      <rect x="6" y="11" width="6" height="1" fill="#4db8ff" />
      <rect x="6" y="13" width="4" height="1" fill="#4db8ff" />
      <rect x="6" y="15" width="5" height="1" fill="#4db8ff" />
      <defs>
        <linearGradient id="newsGradient" x1="2" y1="3" x2="20" y2="21" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1a9fff" />
          <stop offset="1" stopColor="#0066cc" />
        </linearGradient>
      </defs>
    </svg>
  );
};

const handleRefresh = async () => {
  await refreshNews();
  toaster.toast({ title: "Refreshing", body: "Fetching latest news..." });
};

export default definePlugin(() => {
  console.log("DeckyNews initializing");

  const newsRefreshListener = addEventListener<[data: { timestamp: string }]>(
    "news_refreshed",
    (data) => {
      console.log("News refreshed at:", data.timestamp);
    }
  );

  return {
    name: "DeckyNews",
    titleView: (
      <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "3px" }}>
          <ColoredNewsIcon />
          <span>Decky News</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Focusable
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "32px",
              height: "32px",
              borderRadius: "6px",
              background: "rgba(255, 255, 255, 0.05)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              color: "#8b8f98",
              transition: "all 0.2s ease",
              cursor: "pointer",
            }}
            onActivate={handleRefresh}
            onClick={handleRefresh}
          >
            <FaSync style={{ fontSize: "14px" }} />
          </Focusable>
          <Focusable
            style={{ display: "flex", alignItems: "center", padding: "4px", cursor: "pointer" }}
            onActivate={() => setShowSettingsGlobal?.(true)}
            onClick={() => setShowSettingsGlobal?.(true)}
          >
            <FaCog style={{ fontSize: "16px", color: "#8b8f98" }} />
          </Focusable>
        </div>
      </div>
    ),
    content: <MainContent />,
    icon: <ColoredNewsIcon />,
    onDismount() {
      console.log("DeckyNews unloading");
      removeEventListener("news_refreshed", newsRefreshListener);
      setShowSettingsGlobal = null;
    },
    alwaysRender: true,
  };
});
