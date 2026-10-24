import { useState, useEffect, FC } from "react";
import { getCoverageSparkline } from "../api";
import { SparklineData } from "../types";

interface SparklineChartProps {
  similarityHash: string | null;
}

export const SparklineChart: FC<SparklineChartProps> = ({ similarityHash }) => {
  const [sparklineData, setSparklineData] = useState<SparklineData | null>(null);

  useEffect(() => {
    if (similarityHash) {
      getCoverageSparkline(similarityHash)
        .then((data) => setSparklineData(data))
        .catch(() => setSparklineData(null));
    }
  }, [similarityHash]);

  if (!sparklineData || sparklineData.points.length < 2) return null;

  const width = 60;
  const height = 20;
  const points = sparklineData.points;
  const stepX = width / (points.length - 1);

  const pathData = points
    .map((point, i) => {
      const x = i * stepX;
      const y = height - (point.normalized / 100) * height;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

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
      <span style={{ fontSize: "10px", color: "#8b8f98" }}>coverage</span>
    </div>
  );
};
