import { Focusable } from "@decky/ui";
import { FC } from "react";

export interface ActionMenuItem {
  label: string;
  run: () => void;
}

interface ActionMenuProps {
  title: string;
  items: ActionMenuItem[];
  onClose: () => void;
}

export const ActionMenu: FC<ActionMenuProps> = ({ title, items, onClose }) => (
  <Focusable style={{ display: "contents" }} onCancelButton={onClose}>
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000, display: "flex", background: "rgba(0, 0, 0, 0.6)",
        animation: "fadeIn 0.2s ease-out",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          margin: "auto", width: "86%", padding: "6px", borderRadius: "8px",
          background: "#1a2230", border: "1px solid #33405a",
        }}
      >
        <div style={{ margin: "4px 6px 6px", fontSize: "12px", color: "#8b8f98", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {title}
        </div>
        {items.map((it, i) => {
          const go = () => { onClose(); it.run(); };
          return (
            <Focusable key={it.label} autoFocus={i === 0} onActivate={go} onClick={go} style={{ padding: "10px 8px", fontSize: "13px", color: "#fff" }}>
              {it.label}
            </Focusable>
          );
        })}
      </div>
    </div>
  </Focusable>
);
