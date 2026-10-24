import { Focusable } from "@decky/ui";
import { ReactNode } from "react";

export interface FooterItem {
  label: ReactNode;
  onActivate?: () => void;
  disabled?: boolean;
  grow?: number;
  accent?: boolean;
}

export const NavFooter = ({ items }: { items: FooterItem[] }) => (
  <div
    style={{
      position: "sticky", bottom: 0, zIndex: 20, display: "flex", gap: "6px", padding: "6px 10px",
      background: "rgba(14, 20, 27, 0.97)", borderTop: "1px solid rgba(255, 255, 255, 0.08)",
    }}
  >
    {items.map((it, i) => {
      const style: React.CSSProperties = {
        flex: it.grow ?? 1, textAlign: "center", padding: "7px 4px", borderRadius: "5px",
        fontSize: "12px", fontWeight: 600, color: "#fff",
        background: it.accent ? "#1a9fff" : it.onActivate ? "rgba(255, 255, 255, 0.08)" : "transparent",
        opacity: it.disabled ? 0.35 : 1,
      };
      if (!it.onActivate) return <div key={i} style={{ ...style, alignSelf: "center" }}>{it.label}</div>;
      const go = () => { if (!it.disabled) it.onActivate!(); };
      return <Focusable key={i} onActivate={go} onClick={go} style={style}>{it.label}</Focusable>;
    })}
  </div>
);
