import { useState, useEffect, useRef, useCallback, memo } from "react";
import { PanelSectionRow, Focusable, GamepadButton, GamepadEvent } from "@decky/ui";
import { FaExclamationTriangle } from "react-icons/fa";
import { toaster } from "@decky/api";
import { summarizeArticle } from "../api";
import { NewsArticle, LLMStatus, Settings, SummarizeResponse } from "../types";
import { formatRelativeTime, openInBrowser } from "../utils";
import { SparklineChart } from "./SparklineChart";
import { TypewriterText } from "./TypewriterText";

const LONG_PRESS_MOVE_TOLERANCE_PX = 10;

interface NewsItemProps {
  article: NewsArticle;
  health: string;
  llmEnabled: boolean;
  llmStatus: LLMStatus | null;
  settings: Settings;
  index: number;
  onPageChange: (delta: number) => void;
  onShowMenu?: (article: NewsArticle) => void;
  onDismiss?: (link: string) => void;
  onMarkRead?: (link: string) => void;
  command?: { link: string; action: "summarize" } | null;
  onCommandDone?: () => void;
}

export const NewsItem = memo<NewsItemProps>(({ article, health, llmEnabled, llmStatus, settings, index, onPageChange, onShowMenu, onDismiss, onMarkRead, command, onCommandDone }) => {
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [textSource, setTextSource] = useState<SummarizeResponse["text_source"]>();
  const [steps, setSteps] = useState<SummarizeResponse["steps"]>();
  const [expanded, setExpanded] = useState(false);
  const [open, setOpen] = useState(false);
  const longPressTimerRef = useRef<NodeJS.Timeout | null>(null);
  const [isLongPressing, setIsLongPressing] = useState(false);
  const swipeStartXRef = useRef<number | null>(null);
  const swipeStartYRef = useRef(0);
  const [swipeX, setSwipeX] = useState(0);
  const [swipeDismissing, setSwipeDismissing] = useState(false);

  useEffect(() => {
    return () => {
      if (longPressTimerRef.current) clearTimeout(longPressTimerRef.current);
    };
  }, []);


  const handleClick = () => {
    if (isLongPressing) {
      setIsLongPressing(false);
      return;
    }
    if (!open) onMarkRead?.(article.link);
    setOpen(!open);
  };

  const openArticle = () => {
    onMarkRead?.(article.link);
    openInBrowser(article.link);
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    swipeStartXRef.current = e.clientX;
    swipeStartYRef.current = e.clientY;
    longPressTimerRef.current = setTimeout(() => {
      setIsLongPressing(true);
      onShowMenu?.(article);
    }, settings.hoverPreviewDelay);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (swipeStartXRef.current === null) return;
    const deltaX = e.clientX - swipeStartXRef.current;
    const moved = Math.hypot(deltaX, e.clientY - swipeStartYRef.current);
    if (moved > LONG_PRESS_MOVE_TOLERANCE_PX && longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    if (deltaX < -8) setSwipeX(Math.max(-120, deltaX));
  };

  const handlePointerUp = () => {
    const startX = swipeStartXRef.current;
    swipeStartXRef.current = null;

    if (startX !== null && swipeX < -80) {
      setSwipeDismissing(true);
      setTimeout(() => onDismiss?.(article.link), 250);
      setSwipeX(0);
      return;
    }
    setSwipeX(0);

    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }

    if (isLongPressing) {
      setTimeout(() => setIsLongPressing(false), 100);
    }
  };

  const handlePointerLeave = () => {
    swipeStartXRef.current = null;
    setSwipeX(0);
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  };

  const handleSecondaryAction = () => onShowMenu?.(article);


  const handleSummarize = async (e?: React.MouseEvent | CustomEvent) => {
    if (e && 'stopPropagation' in e) e.stopPropagation();

    if (summary) {
      setExpanded(!expanded);
      return;
    }

    setSummarizing(true);
    setSummaryError(null);

    try {
      const result = await summarizeArticle(article.link, article.title);

      if (result.success && result.summary) {
        setSummary(result.summary);
        setTextSource(result.text_source);
        setSteps(result.steps);
        setExpanded(true);
        toaster.toast({
          title: "Summary Generated",
          body: "Article summary ready"
        });
      } else {
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
        setSteps(result.steps);
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

  useEffect(() => {
    if (command?.link !== article.link) return;
    setOpen(true);
    handleSummarize();
    onCommandDone?.();
  }, [command]);

  const handleButtonDown = useCallback((evt: GamepadEvent) => {
    if (evt.detail.button === GamepadButton.TRIGGER_LEFT) onPageChange(-1);
    else if (evt.detail.button === GamepadButton.TRIGGER_RIGHT) onPageChange(1);
  }, [onPageChange]);

  const ACCENT = "#1a9fff";
  const text = (article.content || "").replace(/<[^>]+>/g, "").trim().slice(0, 900);
  const btn = (bg: string, busy = false): React.CSSProperties => ({
    padding: "7px 10px", background: bg, color: "#fff", borderRadius: "5px", fontSize: "12px",
    fontWeight: 600, textAlign: "center", marginTop: "6px", opacity: busy ? 0.7 : 1,
  });

  return (
    <PanelSectionRow>
      <div style={{
        transform: swipeDismissing ? "translateX(-110%)" : `translateX(${swipeX}px)`,
        opacity: swipeDismissing ? 0 : 1,
        transition: swipeX === 0 ? "transform 0.25s ease-out, opacity 0.25s ease-out" : "none",
        animation: `slideInRight 0.3s ease-out ${index * 40}ms both`,
      }}>
        <Focusable
          onActivate={handleClick}
          onClick={handleClick}
          onSecondaryButton={handleSecondaryAction}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerLeave}
          onPointerCancel={handlePointerLeave}
          onButtonDown={handleButtonDown}
          onCancelButton={(e: CustomEvent) => { if (open) { setOpen(false); e.stopPropagation(); } }}
          style={{ userSelect: "none", padding: "5px 6px", borderLeft: `2px solid ${article.is_read ? "#444" : ACCENT}`, opacity: article.is_read ? 0.6 : 1 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "9px", color: "#8b8f98" }}>
            {settings.showSourceIcons && article.favicon_url && (
              <img src={article.favicon_url} alt="" style={{ width: "11px", height: "11px", borderRadius: "50%" }} />
            )}
            <span style={{ color: ACCENT, fontWeight: 700 }}>{article.source}</span>
            {health !== "ok" && <FaExclamationTriangle size={9} color="#ff9f1a" />}
            {summary && <span style={{ color: ACCENT }}>✨</span>}
            <span style={{ marginLeft: "auto" }}>{formatRelativeTime(article.published)}</span>
          </div>
          <div
            style={open
              ? { fontSize: "13px", fontWeight: 600, color: "#fff", lineHeight: 1.3 }
              : { fontSize: "12px", color: "#fff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
          >
            {article.title}
          </div>

          {open && (
            <div>
              {text && <div style={{ fontSize: "12px", lineHeight: 1.45, color: "#c6cad2", marginTop: "4px" }}>{text}</div>}
              {article.similarity_hash && <SparklineChart similarityHash={article.similarity_hash} />}

              {shouldShowButton && (
                <Focusable onActivate={handleSummarize} onClick={handleSummarize}>
                  <div style={btn(ACCENT, summarizing)}>
                    {summarizing ? (
                      <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 3 }}>
                        {[{ height: 8, delay: "0s" }, { height: 14, delay: "0.2s" }, { height: 6, delay: "0.4s" }].map(({ height, delay }, i) => (
                          <span key={i} style={{
                            width: 3, height, borderRadius: 2, background: "currentColor", display: "inline-block",
                            animation: `barWave 1.5s ease-in-out ${delay} infinite`,
                          }} />
                        ))}
                        <span style={{ marginLeft: 5 }}>Summarizing</span>
                      </span>
                    ) : summary ? (expanded ? "Hide Summary" : "Show Summary") : summaryError ? "Retry Summary" : "✨ Summarize"}
                  </div>
                </Focusable>
              )}

              {expanded && summary && (
                <div style={{ marginTop: "6px", padding: "8px", background: "rgba(26, 159, 255, 0.1)", borderLeft: `2px solid ${ACCENT}`, borderRadius: "4px" }}>
                  <TypewriterText text={summary} speed={settings.aiTypewriterSpeed} enabled={settings.aiTypewriterEnabled} />
                  {textSource && (
                    <div style={{ marginTop: "6px", fontSize: "9px", fontWeight: 700, color: textSource === "excerpt" ? "#ffd27a" : "#8b8f98" }}>
                      {{ full: "from full article", alt: "from full article (alternate page)", excerpt: "from feed excerpt (partial)" }[textSource]}
                    </div>
                  )}
                </div>
              )}

              {steps && steps.length > 0 && (textSource !== "full" || summaryError) && (
                <div style={{ marginTop: "6px", padding: "6px", border: "1px solid #243044", borderRadius: "6px", fontSize: "11px" }}>
                  {steps.map((st, i) => (
                    <div key={i} style={{ color: st.status === "ok" ? "#4ade80" : st.status === "failed" ? "#ff6b6b" : "#6b7280" }}>
                      {st.status === "ok" ? "✓" : st.status === "failed" ? "✗" : "↷"} {st.name}{st.detail ? ` - ${st.detail}` : ""}
                    </div>
                  ))}
                </div>
              )}

              {summaryError && (
                <div style={{ marginTop: "6px", padding: "8px", background: "rgba(211, 54, 54, 0.1)", borderRadius: "4px" }}>
                  <div style={{ fontSize: "12px", color: "#d93636", whiteSpace: "pre-wrap" }}>{summaryError}</div>
                </div>
              )}

              <Focusable onActivate={openArticle} onClick={openArticle}>
                <div style={btn("rgba(255,255,255,0.08)")}>Open in browser</div>
              </Focusable>
            </div>
          )}
        </Focusable>
      </div>
    </PanelSectionRow>
  );
});
