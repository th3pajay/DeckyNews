import { useState, useEffect, useRef, useCallback, memo, FC } from "react";
import { PanelSectionRow, Focusable, GamepadButton, GamepadEvent } from "@decky/ui";
import { toaster } from "@decky/api";
import { FaExclamationTriangle } from "react-icons/fa";
import { summarizeArticle, getCoverageSparkline } from "../api";
import {
  NewsArticle,
  LLMStatus,
  SummarizeResponse,
  SparklineData,
  Settings,
  QuickPeekCardProps,
} from "../types";
import { extractDominantColor, formatRelativeTime } from "../utils";

// Suppress unused import warnings — these are used as type references
void ({} as SummarizeResponse);
void ({} as SparklineData);

interface TypewriterTextProps {
  text: string;
  speed: number;
  enabled: boolean;
}

interface SparklineChartProps {
  similarityHash: string | null;
}

interface ArticleCardProps {
  article: NewsArticle;
  health: string;
  viewMode: "compact" | "comfortable" | "magazine";
  isHeroItem: boolean;
  glassmorphismOpacity: number;
  showSourceIcon: boolean;
  accentColor: string;
  children?: React.ReactNode;
}

interface NewsItemProps {
  article: NewsArticle;
  health: string;
  llmEnabled: boolean;
  llmStatus: LLMStatus | null;
  settings: Settings;
  index: number;
  onPageChange: (delta: number) => void;
}

const TypewriterText: FC<TypewriterTextProps> = ({ text, speed, enabled }) => {
  // Use CSS animation for GPU acceleration (no React re-renders)
  if (!enabled) {
    return (
      <div style={{ fontSize: "13px", lineHeight: "1.5", color: "#b8bcbf" }}>
        {text}
      </div>
    );
  }

  // Calculate animation duration based on speed (chars/sec)
  const durationSeconds = text.length / speed;

  // Use CSS animation with max-width + ch units for character-by-character reveal
  // This animates the width of a wrapper, which is GPU-accelerated and doesn't require React state
  const containerStyle: React.CSSProperties = {
    fontSize: "13px",
    lineHeight: "1.5",
    color: "#b8bcbf",
    position: "relative" as const,
    display: "inline-block",
  };

  const typewriterStyle: React.CSSProperties = {
    display: "inline-block",
    overflow: "hidden",
    whiteSpace: "nowrap",
    maxWidth: 0,
    animation: `typewriter-reveal ${durationSeconds}s steps(${text.length}, end) forwards`,
    verticalAlign: "top",
  };

  const cursorStyle: React.CSSProperties = {
    opacity: 0.6,
    animation: "blink 1s step-end infinite",
    marginLeft: "2px",
  };

  return (
    <>
      <style>{`
        @keyframes typewriter-reveal {
          from { max-width: 0; }
          to { max-width: 100%; }
        }
        @keyframes blink {
          0%, 50% { opacity: 0.6; }
          51%, 100% { opacity: 0; }
        }
      `}</style>
      <div style={containerStyle}>
        <span style={typewriterStyle}>{text}</span>
        <span style={cursorStyle}>|</span>
      </div>
    </>
  );
};

const SparklineChart: FC<SparklineChartProps> = ({ similarityHash }) => {
  const [sparklineData, setSparklineData] = useState<SparklineData | null>(null);

  useEffect(() => {
    if (similarityHash) {
      getCoverageSparkline(similarityHash).then(data => setSparklineData(data)).catch(() => setSparklineData(null));
    }
  }, [similarityHash]);

  if (!sparklineData || sparklineData.points.length < 2) return null;

  // Generate SVG path from normalized points
  const width = 60;
  const height = 20;
  const points = sparklineData.points;
  const stepX = width / (points.length - 1);

  const pathData = points.map((point, i) => {
    const x = i * stepX;
    const y = height - (point.normalized / 100) * height;
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <path
          d={pathData}
          fill="none"
          stroke="rgba(26, 159, 255, 0.6)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span style={{ fontSize: "10px", color: "#8b8f98" }}>
        coverage
      </span>
    </div>
  );
};

export const QuickPeekCard: FC<QuickPeekCardProps> = ({ article, onClose }) => {
  const [touchStartY, setTouchStartY] = useState<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);

  const handleTouchStart = (e: React.TouchEvent) => {
    setTouchStartY(e.touches[0].clientY);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (touchStartY === null) return;
    const currentY = e.touches[0].clientY;
    const offset = Math.max(0, currentY - touchStartY);
    setDragOffset(offset);
  };

  const handleTouchEnd = () => {
    if (dragOffset > 100) {
      onClose();
    }
    setDragOffset(0);
    setTouchStartY(null);
  };

  const description = article.content || "No preview available. Tap to read full article.";
  const readTime = Math.max(1, Math.ceil(description.split(' ').length / 200));

  const strippedDescription = description.replace(/<[^>]*>/g, '').substring(0, 300);
  const displayDescription = strippedDescription.length < description.length
    ? strippedDescription + "..."
    : strippedDescription;

  return (
    <>
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.6)",
          backdropFilter: "blur(5px)",
          zIndex: 1000,
          animation: "fadeIn 0.25s ease-out"
        }}
        onClick={onClose}
      />

      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          maxHeight: "70vh",
          backgroundColor: "rgba(27, 40, 56, 0.98)",
          borderRadius: "20px 20px 0 0",
          boxShadow: "0 -4px 24px rgba(0, 0, 0, 0.5)",
          zIndex: 1001,
          animation: "slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
          transform: `translateY(${dragOffset}px)`,
          transition: dragOffset === 0 ? "transform 0.2s ease-out" : "none"
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <div
          style={{
            width: "40px",
            height: "4px",
            backgroundColor: "rgba(255, 255, 255, 0.3)",
            borderRadius: "2px",
            margin: "12px auto 8px",
            cursor: "grab"
          }}
        />
        <Focusable
          style={{
            position: "absolute",
            top: "10px",
            right: "14px",
            background: "none",
            border: "none",
            color: "#8b8f98",
            fontSize: "22px",
            lineHeight: 1,
            padding: "4px 8px",
            cursor: "pointer",
            zIndex: 1002,
          }}
          onActivate={onClose}
          onClick={onClose}
        >
          ×
        </Focusable>

        <div style={{ padding: "0 20px 20px", overflowY: "auto", maxHeight: "calc(70vh - 50px)" }}>
          {article.image_url && (
            <div
              style={{
                width: "100%",
                height: "140px",
                backgroundImage: `url(${article.image_url})`,
                backgroundSize: "cover",
                backgroundPosition: "center",
                borderRadius: "12px",
                marginBottom: "16px"
              }}
            />
          )}

          <h3
            style={{
              fontSize: "16px",
              fontWeight: "600",
              color: "#ffffff",
              marginBottom: "10px",
              lineHeight: "1.4"
            }}
          >
            {article.title}
          </h3>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "14px",
              fontSize: "12px",
              color: "#8b8f98"
            }}
          >
            {article.favicon_url && (
              <img
                src={article.favicon_url}
                alt=""
                style={{ width: "16px", height: "16px", borderRadius: "2px" }}
              />
            )}
            <span style={{ fontWeight: 600 }}>{article.source}</span>
            <span>•</span>
            <span>{formatRelativeTime(article.published)}</span>
            <span>•</span>
            <span>📖 {readTime} min read</span>
          </div>

          <div
            style={{
              fontSize: "14px",
              lineHeight: "1.6",
              color: "#d1d5db",
              marginBottom: "16px"
            }}
          >
            {displayDescription}
          </div>

          <button
            onClick={() => {
              const opened = window.open(article.link, "_blank");
              if (!opened) {
                if (!window.openURL?.(article.link)) {
                  toaster.toast({ title: "Open in browser", body: article.link });
                }
              }
            }}
            style={{
              width: "100%",
              padding: "12px",
              backgroundColor: "rgba(26, 159, 255, 0.15)",
              border: "1px solid rgba(26, 159, 255, 0.4)",
              borderRadius: "8px",
              color: "#1a9fff",
              fontSize: "14px",
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.2s"
            }}
          >
            Open Full Article →
          </button>

          <div
            style={{
              marginTop: "12px",
              textAlign: "center",
              fontSize: "11px",
              color: "#6b7280",
              fontStyle: "italic"
            }}
          >
            Swipe down or tap outside to close
          </div>
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
      `}</style>
    </>
  );
};

const ArticleCard = memo<ArticleCardProps>(({
  article,
  health,
  viewMode,
  isHeroItem,
  glassmorphismOpacity,
  showSourceIcon,
  accentColor,
  children
}) => {
  // Compute glassmorphism styles
  const blurAmount = Math.round(glassmorphismOpacity / 10);
  const bgOpacity = (glassmorphismOpacity / 100) * 0.05;

  const cardBaseStyle = {
    background: `rgba(255, 255, 255, ${bgOpacity + 0.03})`,
    backdropFilter: blurAmount > 0 ? `blur(${blurAmount}px)` : 'none',
    WebkitBackdropFilter: blurAmount > 0 ? `blur(${blurAmount}px)` : 'none',
    border: "1px solid rgba(255, 255, 255, 0.08)",
    borderRadius: "8px",
    marginBottom: "12px",
    boxShadow: "0 2px 4px rgba(0, 0, 0, 0.2)",
    transition: "all 0.2s ease",
  };

  // Compact View
  if (viewMode === "compact") {
    return (
      <div style={{ ...cardBaseStyle, padding: "8px", display: "flex", gap: "8px" }}>
        {article.image_url && (
          <img
            src={article.image_url}
            alt=""
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "4px",
              objectFit: "cover",
              flexShrink: 0
            }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "2px" }}>
            {showSourceIcon && article.favicon_url && (
              <img
                src={article.favicon_url}
                alt=""
                style={{ width: "14px", height: "14px", borderRadius: "50%" }}
              />
            )}
            <span style={{ fontSize: "10px", fontWeight: 700, color: accentColor }}>
              {article.source}
            </span>
            <span style={{ fontSize: "10px", color: "#8b8f98", marginLeft: "auto" }}>
              {formatRelativeTime(article.published)}
            </span>
          </div>
          <div
            style={{
              fontSize: "13px",
              lineHeight: "1.3",
              color: "#ffffff",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical"
            }}
          >
            {article.title}
          </div>
        </div>
      </div>
    );
  }

  // Magazine View (Hero Layout for top 3)
  if (viewMode === "magazine" && isHeroItem) {
    return (
      <div style={{ ...cardBaseStyle, padding: "0", overflow: "hidden" }}>
        {article.image_url && (
          <div
            style={{
              width: "100%",
              height: "180px",
              backgroundImage: `url(${article.image_url})`,
              backgroundSize: "cover",
              backgroundPosition: "center",
              position: "relative"
            }}
          >
            <div
              style={{
                position: "absolute",
                bottom: 0,
                left: 0,
                right: 0,
                height: "100%",
                background: "linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,0.8) 100%)",
                padding: "16px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-end"
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
                {showSourceIcon && article.favicon_url && (
                  <img src={article.favicon_url} alt="" style={{ width: "16px", height: "16px", borderRadius: "50%" }} />
                )}
                <span style={{ fontSize: "11px", fontWeight: 700, color: accentColor }}>
                  {article.source}
                </span>
              </div>
              <div style={{ fontSize: "17px", lineHeight: "1.4", color: "#ffffff", fontWeight: 600 }}>
                {article.title}
              </div>
            </div>
          </div>
        )}
        {children && <div style={{ padding: "14px" }}>{children}</div>}
      </div>
    );
  }

  // Comfortable View (Default)
  return (
    <div style={{ ...cardBaseStyle, padding: "14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
        {health !== "ok" && (
          <span style={{ fontSize: "14px", color: health === "warning" ? "#ffc82c" : "#d93636" }}>
            <FaExclamationTriangle />
          </span>
        )}
        {showSourceIcon && article.favicon_url && (
          <img src={article.favicon_url} alt="" style={{ width: "14px", height: "14px", borderRadius: "50%" }} />
        )}
        <span
          style={{
            fontSize: "11px",
            fontWeight: 700,
            color: accentColor,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}
        >
          {article.source}
        </span>
        <span style={{ fontSize: "11px", color: "#8b8f98", marginLeft: "auto" }}>
          {formatRelativeTime(article.published)}
        </span>
      </div>
      <div style={{ fontSize: "15px", lineHeight: "1.5", color: "#ffffff", fontWeight: 500 }}>
        {article.title}
      </div>
      {children}
    </div>
  );
});

// Skeleton loader component
export const SkeletonArticle: FC = () => {
  return (
    <PanelSectionRow>
      <div
        style={{
          background: "rgba(255, 255, 255, 0.03)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          padding: "14px",
          marginBottom: "12px",
          animation: "shimmer 1.5s infinite"
        }}
      >
        {/* Title skeleton */}
        <div
          style={{
            height: "20px",
            width: "80%",
            backgroundColor: "rgba(255, 255, 255, 0.1)",
            borderRadius: "4px",
            marginBottom: "8px"
          }}
        />

        {/* Metadata skeleton */}
        <div
          style={{
            height: "14px",
            width: "40%",
            backgroundColor: "rgba(255, 255, 255, 0.08)",
            borderRadius: "4px"
          }}
        />
      </div>
    </PanelSectionRow>
  );
};

export const NewsItem = memo<NewsItemProps>(({ article, health, llmEnabled, llmStatus, settings, index, onPageChange }) => {
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [accentColor, setAccentColor] = useState<string>("#1a9fff");
  const longPressTimerRef = useRef<NodeJS.Timeout | null>(null);
  const autoDismissTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [showHoverPreview, setShowHoverPreview] = useState(false);
  const [isLongPressing, setIsLongPressing] = useState(false);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
      if (autoDismissTimerRef.current) clearTimeout(autoDismissTimerRef.current);
    };
  }, []);


  const handleClick = () => {
    // Prevent normal click if long-pressing
    if (isLongPressing) {
      setIsLongPressing(false);
      return;
    }
    const opened = window.open(article.link, "_blank");
    if (!opened) {
      if (!window.openURL?.(article.link)) {
        toaster.toast({ title: "Open in browser", body: article.link });
      }
    }
  };

  const handlePointerDown = () => {
    if (!settings?.enableHoverPreview) return;

    longPressTimerRef.current = setTimeout(() => {
      setIsLongPressing(true);
      setShowHoverPreview(true);
    }, settings.hoverPreviewDelay);
  };

  const handlePointerUp = () => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }

    // Close modal if long-pressing
    if (isLongPressing) {
      setShowHoverPreview(false);
      // Delay resetting isLongPressing to prevent handleClick from triggering
      setTimeout(() => setIsLongPressing(false), 100);
    }
  };

  const handlePointerLeave = () => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  };

  const handleSecondaryAction = () => {
    if (!settings?.enableHoverPreview) return;

    // Toggle preview modal
    setShowHoverPreview(!showHoverPreview);

    // Set up auto-dismiss timer (30 seconds)
    if (!showHoverPreview) {
      autoDismissTimerRef.current = setTimeout(() => {
        setShowHoverPreview(false);
      }, 30000);
    } else {
      // Clear timer if closing
      if (autoDismissTimerRef.current) {
        clearTimeout(autoDismissTimerRef.current);
        autoDismissTimerRef.current = null;
      }
    }
  };


  const handleSummarize = async (e: React.MouseEvent | CustomEvent) => {
    if ('stopPropagation' in e) e.stopPropagation();

    if (summary) {
      // Toggle visibility if already summarized
      setExpanded(!expanded);
      return;
    }

    setSummarizing(true);
    setSummaryError(null);

    try {
      const result = await summarizeArticle(article.link, article.title);

      if (result.success && result.summary) {
        setSummary(result.summary);
        setExpanded(true);
        toaster.toast({
          title: "Summary Generated",
          body: "Article summary ready"
        });
      } else {
        // Build detailed error message with diagnostics if available
        const diagnostics = result.diagnostics;
        let errorDetail = '';
        if (diagnostics) {
          errorDetail = `\n\nDiagnostics:\nModel: ${diagnostics.model_exists ? 'Found' : 'MISSING'} (${diagnostics.model_path})\nBinary: ${diagnostics.binary_exists ? 'Found' : 'MISSING'}`;
          if (!diagnostics.binary_exists) {
            errorDetail += '\nBinary paths checked:';
            for (const [path, status] of Object.entries(diagnostics.binary_candidates_checked || {})) {
              const s = status as { exists: boolean; executable: boolean };
              errorDetail += `\n  ${path}: ${s.exists ? (s.executable ? 'OK' : 'not executable') : 'not found'}`;
            }
          }
          console.error("Summarize failed:", result.error, diagnostics);
        }
        setSummaryError((result.error || "Failed to generate summary") + errorDetail);
        toaster.toast({
          title: "Summary Failed",
          body: result.error || "Unknown error"
        });
      }
    } catch (error) {
      setSummaryError("Failed to connect to backend");
      console.error("Summarize error:", error);
    } finally {
      setSummarizing(false);
    }
  };

  const shouldShowButton = llmEnabled && llmStatus?.model_downloaded;

  const handleButtonDown = useCallback((evt: GamepadEvent) => {
    if (evt.detail.button === GamepadButton.TRIGGER_LEFT) onPageChange(-1);
    else if (evt.detail.button === GamepadButton.TRIGGER_RIGHT) onPageChange(1);
  }, [onPageChange]);

  // Extract accent color from static logo
  useEffect(() => {
    if (settings.accentColorSource === "automatic" && article.image_url) {
      const cacheKey = `color_${article.source}`;
      const cached = sessionStorage.getItem(cacheKey);

      if (cached) {
        setAccentColor(cached);
      } else {
        extractDominantColor(article.image_url).then(color => {
          setAccentColor(color);
          sessionStorage.setItem(cacheKey, color);
        });
      }
    } else {
      setAccentColor("#1a9fff");
    }
  }, [article.image_url, article.source, settings.accentColorSource]);

  const isHeroItem = settings.uiViewMode === "magazine" && index < 3;

  return (
    <PanelSectionRow>
      <Focusable
        onActivate={handleClick}
        onClick={handleClick}
        onSecondaryButton={handleSecondaryAction}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerLeave}
        onButtonDown={handleButtonDown}
      >
        <ArticleCard
          article={article}
          health={health}
          viewMode={settings.uiViewMode}
          isHeroItem={isHeroItem}
          glassmorphismOpacity={settings.glassmorphismOpacity}
          showSourceIcon={settings.showSourceIcons}
          accentColor={accentColor}
        >
          {article.similarity_hash && (
            <SparklineChart
              similarityHash={article.similarity_hash}
            />
          )}

          {shouldShowButton && (
            <div style={{ marginTop: "12px" }}>
              <Focusable onActivate={handleSummarize} onClick={handleSummarize}>
                <div
                  style={{
                    padding: "8px 12px",
                    background: accentColor,
                    color: "#ffffff",
                    borderRadius: "6px",
                    fontSize: "12px",
                    fontWeight: 600,
                    textAlign: "center",
                    cursor: "pointer",
                    opacity: summarizing ? 0.7 : 1,
                    transition: "opacity 0.2s ease"
                  }}
                >
                  {summarizing ? (
                    <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 3 }}>
                      {([
                        { height: 8,  delay: "0s"   },
                        { height: 14, delay: "0.2s" },
                        { height: 6,  delay: "0.4s" },
                      ]).map(({ height, delay }, i) => (
                        <span key={i} style={{
                          width: 3, height, borderRadius: 2,
                          background: "currentColor",
                          display: "inline-block",
                          animation: `barWave 1.5s ease-in-out ${delay} infinite`,
                        }} />
                      ))}
                      <span style={{ marginLeft: 5 }}>Summarizing</span>
                    </span>
                  ) : summary ? (
                    expanded ? "Hide Summary" : "Show Summary"
                  ) : (
                    "Summarize"
                  )}
                </div>
              </Focusable>

              {expanded && summary && (
                <div style={{ marginTop: "8px", padding: "10px", background: "rgba(0, 0, 0, 0.2)", borderRadius: "6px" }}>
                  <TypewriterText
                    text={summary}
                    speed={settings.aiTypewriterSpeed}
                    enabled={settings.aiTypewriterEnabled}
                  />
                </div>
              )}

              {summaryError && (
                <div style={{ marginTop: "8px", padding: "10px", background: "rgba(211, 54, 54, 0.1)", borderRadius: "6px" }}>
                  <div style={{ fontSize: "12px", color: "#d93636" }}>{summaryError}</div>
                </div>
              )}
            </div>
          )}
        </ArticleCard>
      </Focusable>

      {showHoverPreview && settings?.enableHoverPreview && (
        <QuickPeekCard
          article={article}
          onClose={() => setShowHoverPreview(false)}
        />
      )}
    </PanelSectionRow>
  );
});
