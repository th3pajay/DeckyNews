import {
  PanelSection,
  PanelSectionRow,
  staticClasses,
  Focusable,
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  definePlugin
} from "@decky/api";
import { useState, useEffect, useLayoutEffect, useRef, FC, Component } from "react";
import { FaCog, FaSync } from "react-icons/fa";

import { NewsArticle } from "./types";
import { useArticleFeed } from "./hooks/useArticleFeed";
import { usePullToRefresh } from "./hooks/usePullToRefresh";
import { pullText } from "./feedLogic";
import { NewsItem } from "./components/NewsItem";
import { SkeletonArticle } from "./components/SkeletonArticle";
import { QuickPeekCard } from "./components/QuickPeekCard";
import { ActionMenu } from "./components/ActionMenu";
import { NavFooter } from "./components/NavFooter";
import { findScroller, openInBrowser } from "./utils";

import { Settings as SettingsComponent } from "./components/Settings";

declare global {
  interface Window {
    openURL?: (url: string) => boolean | void;
    SteamClient?: { Input?: { RegisterForControllerStateChanges?: (cb: (changes: Array<{ ulButtons: number }>) => void) => { unregister: () => void } } };
  }
}

let animationsInjected = false;
function injectGlobalAnimations() {
  if (animationsInjected) return;
  animationsInjected = true;
  const style = document.createElement('style');
  style.innerHTML = `
    @keyframes shimmer { 0%,100% { opacity:0.6; } 50% { opacity:1; } }
    @keyframes blink { 0%,50% { opacity:1; } 51%,100% { opacity:0; } }
    @keyframes spin { from { transform:rotate(0deg); } to { transform:rotate(360deg); } }
    @keyframes barWave { 0%,100% { opacity:0.15; } 50% { opacity:1; } }
    @keyframes slideInRight { from { transform:translateX(20px); opacity:0; } to { transform:translateX(0); opacity:1; } }
  `;
  document.head.appendChild(style);
}

const StatusPill: FC<{ label: string; color: string }> = ({ label, color }) => (
  <div style={{ display: "flex", alignItems: "center", gap: "5px", padding: "2px 12px 4px", justifyContent: "flex-end" }}>
    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: color, display: "inline-block" }} />
    <span style={{ fontSize: "10px", fontWeight: 600, color }}>{label}</span>
  </div>
);

function Content({ showSettings, onBackToNews }: { showSettings?: boolean; onBackToNews?: () => void }) {
  const feed = useArticleFeed(showSettings);
  const { visible, page, totalPages, loading, refreshing, sourceHealth, llmStatus, fadeIn, settings, sources,
    pendingDismiss, activeSource, setActiveSource, newArticleCount,
    handlePageChange, handleMarkRead, handleMarkUnread, handleDismiss, handleUndoDismiss, handlePrevPage, handleNextPage } = feed;
  const { pullStage, pullIndicatorRef, pullSpinnerRef, touchHandlers } = usePullToRefresh(refreshing, feed.handleRefresh);
  const [previewArticle, setPreviewArticle] = useState<NewsArticle | null>(null);
  const [menuLink, setMenuLink] = useState<string | null>(null);
  const [command, setCommand] = useState<{ link: string; action: "summarize" } | null>(null);
  const menuArticle = visible.find(a => a.link === menuLink);

  const wrapRef = useRef<HTMLDivElement>(null);
  const savedScroll = useRef(0);
  const settingsOpen = useRef(false);
  settingsOpen.current = !!showSettings;

  useEffect(() => {
    const sc = findScroller(wrapRef.current);
    if (!sc) return;
    const onScroll = () => { if (!settingsOpen.current) savedScroll.current = sc.scrollTop; };
    sc.addEventListener("scroll", onScroll);
    return () => sc.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    const sc = findScroller(wrapRef.current);
    if (sc) sc.scrollTop = showSettings ? 0 : savedScroll.current;
  }, [showSettings]);

  const turnPage = (fn: () => void) => {
    fn();
    const sc = findScroller(wrapRef.current);
    if (sc) sc.scrollTop = 0;
  };

  return (
    <div ref={wrapRef} onContextMenu={(e) => e.preventDefault()}>
    {showSettings && onBackToNews && <SettingsComponent onBack={onBackToNews} />}
    <Focusable
      style={{ position: "relative", overflow: "hidden", display: showSettings ? "none" : undefined }}
      {...touchHandlers}
    >
      {pullStage > 0 && !refreshing && (
        <div
          ref={pullIndicatorRef}
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
            transform: "translateY(0px)",
            opacity: 0,
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
              ref={pullSpinnerRef}
              style={{
                width: "40px",
                height: "40px",
                borderRadius: "50%",
                border: "3px solid rgba(26, 159, 255, 0.2)",
                borderTopColor: "#1a9fff",
                transform: "rotate(0deg)",
                transition: "all 0.3s ease",
                animation: refreshing ? "spin 1s linear infinite" : "none",
              }}
            />
            {pullStage === 3 && !refreshing && (
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
              color: pullStage >= 2 ? "#1a9fff" : "#8b8f98",
            }}
          >
            {pullText(pullStage, refreshing)}
          </div>
        </div>
      )}

      <StatusPill
        label={newArticleCount > 0 ? `${newArticleCount} new` : "Up to date"}
        color={newArticleCount > 0 ? "#1a9fff" : "#4ade80"}
      />

      <div style={{ overflowX: "auto", display: "flex", gap: "6px", padding: "0 12px 8px", scrollbarWidth: "none" } as React.CSSProperties}>
        {["All", ...sources].map(src => (
          <Focusable
            key={src}
            onActivate={() => setActiveSource(src)}
            onClick={() => setActiveSource(src)}
            style={{
              flexShrink: 0,
              padding: "4px 10px",
              borderRadius: "12px",
              fontSize: "11px",
              fontWeight: 600,
              background: activeSource === src ? "rgba(26, 159, 255, 0.2)" : "rgba(255,255,255,0.06)",
              border: `1px solid ${activeSource === src ? "rgba(26, 159, 255, 0.5)" : "rgba(255,255,255,0.1)"}`,
              color: activeSource === src ? "#1a9fff" : "#8b8f98",
              transition: "all 0.2s ease",
              cursor: "pointer",
            }}
          >{src}</Focusable>
        ))}
      </div>

      <PanelSection>
        <div
          style={{
            opacity: fadeIn ? 1 : 0,
            transition: "opacity 0.5s ease-in-out"
          }}
        >
          {!settings || (loading && feed.articles.length === 0) ? (
            <>
              {Array.from({ length: 10 }).map((_, i) => (
                <SkeletonArticle key={`skeleton-${i}`} />
              ))}
            </>
          ) : feed.articles.length === 0 ? (
            <PanelSectionRow>
              <div style={{ textAlign: "center", padding: "20px", color: "#8b8f98" }}>
                No news available - try refreshing
              </div>
            </PanelSectionRow>
          ) : (
            visible.map((article, idx) => (
              <NewsItem
                key={article.link}
                article={article}
                health={sourceHealth[article.source] || 'ok'}
                llmEnabled={llmStatus?.enabled ?? false}
                llmStatus={llmStatus}
                settings={settings}
                index={idx}
                onPageChange={handlePageChange}
                onShowMenu={(a) => setMenuLink(a.link)}
                onDismiss={handleDismiss}
                onMarkRead={handleMarkRead}
                command={command}
                onCommandDone={() => setCommand(null)}
              />
            ))
          )}
        </div>
      </PanelSection>

      {pendingDismiss && (
        <div style={{
          position: "absolute", bottom: "56px", left: "12px", right: "12px",
          background: "rgba(27, 40, 56, 0.96)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "8px", padding: "10px 14px",
          display: "flex", justifyContent: "space-between", alignItems: "center",
          zIndex: 500, animation: "slideUp 0.2s ease-out",
        }}>
          <span style={{ fontSize: "12px", color: "#d1d5db" }}>Article removed</span>
          <Focusable
            onActivate={handleUndoDismiss}
            onClick={handleUndoDismiss}
            style={{ fontSize: "12px", color: "#1a9fff", fontWeight: 600, background: "none", border: "none", cursor: "pointer" }}
          >Undo</Focusable>
        </div>
      )}

      {menuArticle && (
        <ActionMenu
          title={menuArticle.title}
          onClose={() => setMenuLink(null)}
          items={[
            { label: "Quick peek", run: () => { setPreviewArticle(menuArticle); handleMarkRead(menuArticle.link); } },
            ...(llmStatus?.enabled && llmStatus?.model_downloaded
              ? [{ label: "Summarize", run: () => setCommand({ link: menuArticle.link, action: "summarize" }) }]
              : []),
            menuArticle.is_read
              ? { label: "Mark unread", run: () => handleMarkUnread(menuArticle.link) }
              : { label: "Mark read", run: () => handleMarkRead(menuArticle.link) },
            { label: "Open in browser", run: () => { handleMarkRead(menuArticle.link); openInBrowser(menuArticle.link); } },
            { label: "Dismiss", run: () => handleDismiss(menuArticle.link) },
          ]}
        />
      )}

      {previewArticle && (
        <QuickPeekCard
          article={previewArticle}
          onClose={() => setPreviewArticle(null)}
        />
      )}
    </Focusable>
    {!showSettings && (
      <NavFooter
        items={[
          ...(totalPages > 1 ? [
            { label: "‹", onActivate: () => turnPage(handlePrevPage), disabled: page === 1 || loading },
            { label: `${page} / ${totalPages}`, grow: 1.4 },
            { label: "›", onActivate: () => turnPage(handleNextPage), disabled: page === totalPages || loading },
          ] : []),
          { label: <FaSync style={{ fontSize: "12px" }} />, onActivate: feed.handleRefresh, disabled: refreshing },
          { label: <FaCog style={{ fontSize: "12px" }} />, onActivate: () => setShowSettingsGlobal?.(true) },
        ]}
      />
    )}
    </div>
  );
}

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

  useEffect(() => { injectGlobalAnimations(); }, []);

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

export default definePlugin(() => {
  const newsRefreshListener = addEventListener<[data: { timestamp: string }]>(
    "news_refreshed",
    () => {}
  );

  return {
    name: "DeckyNews",
    titleView: (
      <div className={staticClasses.Title} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "3px" }}>
          <ColoredNewsIcon />
          <span>Decky News</span>
        </div>
      </div>
    ),
    content: <MainContent />,
    icon: <ColoredNewsIcon />,
    onDismount() {
      removeEventListener("news_refreshed", newsRefreshListener);
      setShowSettingsGlobal = null;
    },
    alwaysRender: true,
  };
});
