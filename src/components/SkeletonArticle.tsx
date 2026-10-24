import { FC } from "react";
import { PanelSectionRow } from "@decky/ui";

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
          animation: "shimmer 1.5s infinite",
        }}
      >
        <div
          style={{
            height: "20px",
            width: "80%",
            backgroundColor: "rgba(255, 255, 255, 0.1)",
            borderRadius: "4px",
            marginBottom: "8px",
          }}
        />
        <div
          style={{
            height: "14px",
            width: "40%",
            backgroundColor: "rgba(255, 255, 255, 0.08)",
            borderRadius: "4px",
          }}
        />
      </div>
    </PanelSectionRow>
  );
};
