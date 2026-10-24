import { FC } from "react";

interface TypewriterTextProps {
  text: string;
  speed: number;
  enabled: boolean;
}

export const TypewriterText: FC<TypewriterTextProps> = ({ text, speed, enabled }) => {
  if (!enabled) {
    return (
      <div style={{ fontSize: "13px", lineHeight: "1.5", color: "#b8bcbf" }}>
        {text}
      </div>
    );
  }

  const durationSeconds = text.length / speed;

  const containerStyle: React.CSSProperties = {
    fontSize: "13px",
    lineHeight: "1.5",
    color: "#b8bcbf",
    position: "relative",
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
