import { useState, FC } from "react";
import { Focusable } from "@decky/ui";
import { toaster } from "@decky/api";
import { QuickPeekCardProps } from "../types";
import { formatRelativeTime } from "../utils";

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
  const readTime = Math.max(1, Math.ceil(description.split(" ").length / 200));

  const strippedDescription = description.replace(/<[^>]*>/g, "").substring(0, 300);
  const displayDescription =
    strippedDescription.length < description.length ? strippedDescription + "..." : strippedDescription;

  return (
    <Focusable style={{ display: "contents" }} onCancelButton={onClose}>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "rgba(0, 0, 0, 0.6)",
          backdropFilter: "blur(5px)",
          zIndex: 1000,
          animation: "fadeIn 0.25s ease-out",
        }}
        onClick={onClose}
      />

      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          maxHeight: "70%",
          backgroundColor: "rgba(27, 40, 56, 0.98)",
          borderRadius: "20px 20px 0 0",
          boxShadow: "0 -4px 24px rgba(0, 0, 0, 0.5)",
          zIndex: 1001,
          animation: "slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
          transform: `translateY(${dragOffset}px)`,
          transition: dragOffset === 0 ? "transform 0.2s ease-out" : "none",
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
            cursor: "grab",
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

        <div style={{ padding: "0 20px 20px", overflowY: "auto", maxHeight: "calc(70% - 50px)" }}>
          {article.image_url && (
            <div
              style={{
                width: "100%",
                height: "140px",
                backgroundImage: `url(${article.image_url})`,
                backgroundSize: "cover",
                backgroundPosition: "center",
                borderRadius: "12px",
                marginBottom: "16px",
              }}
            />
          )}

          <h3
            style={{
              fontSize: "16px",
              fontWeight: "600",
              color: "#ffffff",
              marginBottom: "10px",
              lineHeight: "1.4",
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
              color: "#8b8f98",
            }}
          >
            {article.favicon_url && (
              <img src={article.favicon_url} alt="" style={{ width: "16px", height: "16px", borderRadius: "2px" }} />
            )}
            <span style={{ fontWeight: 600 }}>{article.source}</span>
            <span>•</span>
            <span>{formatRelativeTime(article.published)}</span>
            <span>•</span>
            <span>📖 {readTime} min read</span>
          </div>

          <div style={{ fontSize: "14px", lineHeight: "1.6", color: "#d1d5db", marginBottom: "16px" }}>
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
              transition: "all 0.2s",
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
              fontStyle: "italic",
            }}
          >
            Swipe down, tap outside, or press B to close
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
    </Focusable>
  );
};
