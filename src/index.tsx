import {
  PanelSection,
  PanelSectionRow,
  staticClasses,
  Focusable,
  ToggleField,
  SliderField,
  DropdownItem,
  SingleDropdownOption,
  GamepadButton,
  GamepadEvent
} from "@decky/ui";
import {
  addEventListener,
  removeEventListener,
  callable,
  definePlugin,
  toaster
} from "@decky/api";
import { useState, useEffect, useRef, FC, Component } from "react";
import { FaExclamationTriangle, FaCog, FaSync, FaSpinner, FaChevronLeft, FaChevronRight, FaTrash, FaDownload } from "react-icons/fa";

// Add shimmer animation CSS
const shimmerStyle = document.createElement('style');
shimmerStyle.innerHTML = `
  @keyframes shimmer {
    0% {
      opacity: 0.6;
    }
    50% {
      opacity: 1;
    }
    100% {
      opacity: 0.6;
    }
  }
`;
document.head.appendChild(shimmerStyle);

// Add blink animation CSS for typewriter cursor
const blinkStyle = document.createElement('style');
blinkStyle.innerHTML = `
  @keyframes blink {
    0%, 50% { opacity: 1; }
    51%, 100% { opacity: 0; }
  }
`;
document.head.appendChild(blinkStyle);

// Add spin animation CSS for loading spinners
const spinStyle = document.createElement('style');
spinStyle.innerHTML = `
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
`;
document.head.appendChild(spinStyle);

const getNews = callable<[page: number, items_per_page: number], NewsFeedResponse>("get_news");
const refreshNews = callable<[], boolean>("refresh_news");
const getSourceHealth = callable<[], SourceHealth>("get_source_health");
const getSettings = callable<[], Settings>("get_settings");
const updateSettings = callable<[settings: Partial<Settings>], boolean>("update_settings");

// LLM Summarization API
const summarizeArticle = callable<[url: string, title: string], SummarizeResponse>("summarize_article");
const getLLMStatus = callable<[], LLMStatus>("get_llm_status");
const downloadLLMModel = callable<[], DownloadResponse>("download_llm_model");
const unloadLLMModel = callable<[], boolean>("unload_llm_model");
const deleteLLMModel = callable<[], boolean>("delete_llm_model");

// UI Enhancement API
const getCoverageSparkline = callable<[hash: string], SparklineData>("get_coverage_sparkline");

// Telemetry API
const getTelemetryHeatmap = callable<[hours: number], TelemetryHeatmapResponse>("get_telemetry_heatmap");
const exportTelemetryDossier = callable<[], ExportDossierResponse>("export_telemetry_dossier");
const clearTelemetryData = callable<[], { success: boolean }>("clear_telemetry_data");


// LLM Types
interface RateLimiterStatus {
  cooldown_remaining_seconds: number;
  can_request: boolean;
  reason: string;
}

interface ResourceStatus {
  memory_available_mb: number;
  memory_percent_used: number;
  cpu_temp_celsius: number | null;
  can_proceed: boolean;
}

interface CircuitBreakerStatus {
  state: "closed" | "open" | "half_open";
  failure_count: number;
  last_failure: string | null;
}

interface LLMStatus {
  enabled: boolean;
  binary_available: boolean;
  model_downloaded: boolean;
  model_loaded: boolean;
  model_loading: boolean;
  download_progress: number;
  selected_model?: string;
  model_display_name?: string;
  model_size_mb?: number;
  experimental?: boolean;
  circuit_breaker: CircuitBreakerStatus;
  rate_limiter: RateLimiterStatus;
  resources: ResourceStatus;
  diagnostics?: LoadDiagnostics;
}

interface BinaryCandidateStatus {
  exists: boolean;
  executable: boolean;
}

interface LoadDiagnostics {
  model_path: string;
  model_exists: boolean;
  model_size_bytes: number;
  binary_path: string | null;
  binary_exists: boolean;
  binary_candidates_checked: Record<string, BinaryCandidateStatus>;
  plugin_dir: string;
  runtime_dir: string;
}

interface SummarizeResponse {
  success: boolean;
  summary: string | null;
  error: string | null;
  status: LLMStatus | null;
  diagnostics?: LoadDiagnostics;
}

interface DownloadResponse {
  success: boolean;
  error?: string;
  status: LLMStatus;
}

// Base types for news data
interface NewsArticle {
  title: string;
  link: string;
  published: string;
  source: string;
  content?: string;
  image_url?: string;
  favicon_url?: string;
  similarity_hash?: string;
}

interface SparklinePoint {
  hour: string;
  count: number;
  normalized: number;
}

interface SparklineData {
  points: SparklinePoint[];
  max_count: number;
}

// Telemetry interfaces
interface HeatmapCell {
  id: number;
  timestamp: number;
  engine_type: string;
  model_id: string | null;
  tps: number | null;
  ttft: number | null;
  prompt_eval_time: number | null;
  total_tokens: number | null;
  stop_reason: string | null;
  ram_delta_mb: number | null;
  load_duration: number | null;
  cpu_peak_temp: number | null;
  temp_delta: number | null;
  tdp_watts: number | null;
  fan_rpm: number | null;
  energy_mwh: number | null;
  cooldown_vel: number | null;
  comp_ratio: number | null;
  flesch_score: number | null;
  ai_probability: number | null;
  dup_count: number | null;
  dedup_lat: number | null;
  ttl_days: number | null;
  fetch_lat: number | null;
  src_success: number | null;
  cloud_bypass: number | null;
  dl_kbps: number | null;
  ipc_lat: number | null;
  press_dur: number | null;
  ui_fps_drop: number | null;
}

interface TelemetryHeatmapResponse {
  success: boolean;
  data?: HeatmapCell[];
  error?: string;
}

interface ExportDossierResponse {
  success: boolean;
  path?: string;
  error?: string;
}

interface NewsFeedResponse {
  articles: NewsArticle[];
  total: number;
  page: number;
  totalPages: number;
}

interface Settings {
  refreshInterval: number;
  debugMode: boolean;
  sourcesEnabled: string[];
  analyticsOptIn: boolean;
  llmEnabled: boolean;
  llmCooldownSeconds: number;
  llmResourceMonitoringEnabled: boolean;
  uiViewMode: "compact" | "comfortable" | "magazine";
  showSourceIcons: boolean;
  glassmorphismOpacity: number;
  accentColorSource: "automatic" | "default";
  dynamicBackdropEnabled: boolean;
  aiTypewriterEnabled: boolean;
  aiTypewriterSpeed: number;
  enableHoverPreview: boolean;
  hoverPreviewDelay: number;
  aiPersonality: "analyst" | "tldr";
  performanceGuardEnabled: boolean;
  ramThresholdMB: number;
  articleRetention: number;
  allowLlmDuringGaming: boolean;
  llmTempCeilingCelsius: number;
  llmThermalCooldownBonus: number;
  llmAdaptiveTokens: boolean;
  llmReducedTokenCount: number;
  llmAdaptiveThreads: boolean;
  selectedModel: string;
}

interface SourceHealth {
  [key: string]: "ok" | "warning" | "error";
}

interface QuickPeekCardProps {
  article: NewsArticle;
  onClose: () => void;
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0, s = 0, l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }

  return [h, s, l];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  let r, g, b;

  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    };

    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }

  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

async function extractDominantColor(imageUrl: string): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "Anonymous";

    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        if (!ctx) {
          resolve('#1a9fff');
          return;
        }

        // Resize to 50x50 for performance
        canvas.width = 50;
        canvas.height = 50;
        ctx.drawImage(img, 0, 0, 50, 50);

        const imageData = ctx.getImageData(0, 0, 50, 50);
        const pixels = imageData.data;

        // Simple color clustering: average RGB, skip too dark/light
        let r = 0, g = 0, b = 0, count = 0;

        for (let i = 0; i < pixels.length; i += 4) {
          const pr = pixels[i];
          const pg = pixels[i + 1];
          const pb = pixels[i + 2];
          const brightness = (pr + pg + pb) / 3;

          // Skip near-black and near-white
          if (brightness > 40 && brightness < 215) {
            r += pr;
            g += pg;
            b += pb;
            count++;
          }
        }

        if (count === 0) {
          resolve('#1a9fff');
          return;
        }

        r = Math.round(r / count);
        g = Math.round(g / count);
        b = Math.round(b / count);

        // Boost saturation by 30%
        const [h, s, l] = rgbToHsl(r, g, b);
        const boostedS = Math.min(s + 0.3, 1);
        const [nr, ng, nb] = hslToRgb(h, boostedS, l);

        const hex = `#${nr.toString(16).padStart(2, '0')}${ng.toString(16).padStart(2, '0')}${nb.toString(16).padStart(2, '0')}`;
        resolve(hex);
      } catch (err) {
        resolve('#1a9fff');
      }
    };

    img.onerror = () => resolve('#1a9fff');
    img.src = imageUrl;
  });
}



interface TypewriterTextProps {
  text: string;
  speed: number;
  enabled: boolean;
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

interface SparklineChartProps {
  similarityHash: string | null;
  similarCount: number;
}

const SparklineChart: FC<SparklineChartProps> = ({ similarityHash, similarCount }) => {
  const [sparklineData, setSparklineData] = useState<SparklineData | null>(null);

  useEffect(() => {
    if (similarityHash && similarCount >= 5) {
      getCoverageSparkline(similarityHash).then(data => setSparklineData(data)).catch(() => setSparklineData(null));
    }
  }, [similarityHash, similarCount]);

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
        {similarCount} sources
      </span>
    </div>
  );
};

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



interface HeatmapCellProps {
  data: HeatmapCell;
  isFocused: boolean;
  colorBy: 'tps' | 'temp';
  onClick: () => void;
}

const HeatmapCell: FC<HeatmapCellProps> = ({ data, isFocused, colorBy, onClick }) => {
  const tps = data.tps ?? 0;
  const rawIntensity = colorBy === 'temp'
    ? Math.min(1, (data.cpu_peak_temp ?? 0) / 100)
    : Math.min(1, tps / 50);

  // 4-color gradient: blue → green → yellow → red
  // Alpha is smoothly interpolated within each 0.25-wide band (0.4 → 1.0)
  const getColor = (val: number): string => {
    const bandAlpha = (bandVal: number) => 0.4 + (bandVal / 0.25) * 0.6;
    if (val < 0.25) return `rgba(26, 159, 255, ${bandAlpha(val)})`; // Blue (cold)
    if (val < 0.5)  return `rgba(76, 175, 80, ${bandAlpha(val - 0.25)})`; // Green (good)
    if (val < 0.75) return `rgba(255, 193, 7, ${bandAlpha(val - 0.5)})`; // Yellow (warm)
    return `rgba(244, 67, 54, ${bandAlpha(val - 0.75)})`; // Red (hot)
  };
  const intensity = rawIntensity;

  const cellStyle: React.CSSProperties = {
    background: getColor(intensity),
    border: isFocused ? '2px solid #1a9fff' : '1px solid #3d4450',
    borderRadius: '4px',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    alignItems: 'center',
    fontSize: '11px',
    cursor: 'pointer',
    padding: '4px',
    transition: 'all 0.2s',
    minHeight: '60px',
  };

  return (
    <Focusable style={cellStyle} onActivate={onClick}>
      <div style={{ fontWeight: 600, color: '#e8eaed' }}>
        {tps > 0 ? `${tps.toFixed(1)}` : '—'}
      </div>
      <div style={{ fontSize: '9px', opacity: 0.7, color: '#b8bcbf' }}>
        {data.cpu_peak_temp ? `${data.cpu_peak_temp.toFixed(0)}°C` : ''}
      </div>
    </Focusable>
  );
};

// Thresholds derived from main.py resource limits (75°C gaming / 80°C normal, 500MB/800MB RAM)
const METRIC_THRESHOLDS: Record<string, { good: [number, number]; warn: [number, number] }> = {
  tps:           { good: [5, 50],    warn: [1, 5] },
  ttft:          { good: [0, 2000],  warn: [2000, 5000] },
  cpu_peak_temp: { good: [0, 75],    warn: [75, 85] },
  temp_delta:    { good: [0, 10],    warn: [10, 20] },
  flesch_score:  { good: [40, 100],  warn: [20, 40] },
  ai_probability:{ good: [0, 0.4],   warn: [0.4, 0.7] },
  src_success:   { good: [80, 100],  warn: [50, 80] },
  comp_ratio:    { good: [2, 10],    warn: [1, 2] },
  ram_delta_mb:  { good: [0, 200],   warn: [200, 500] },
};

interface MetricRow { label: string; key: string; value: any; unit: string; }

interface MetricInspectorProps {
  cell: HeatmapCell;
  onClose: () => void;
}

const MetricInspector: FC<MetricInspectorProps> = ({ cell, onClose }) => {
  const STATUS_GREEN = "#4ade80";
  const STATUS_YELLOW = "#ffc82c";
  const STATUS_RED = "#d93936";

  const getMetricColor = (key: string, value: number): string => {
    const t = METRIC_THRESHOLDS[key];
    if (!t) return '#e8eaed';
    if (value >= t.good[0] && value <= t.good[1]) return STATUS_GREEN;
    if (value >= t.warn[0] && value <= t.warn[1]) return STATUS_YELLOW;
    return STATUS_RED;
  };

  const formatValue = (val: any, unit: string = ''): string => {
    if (val === null || val === undefined) return 'N/A';
    if (typeof val === 'number') return `${val.toFixed(2)} ${unit}`.trim();
    return `${val} ${unit}`.trim();
  };

  const sections: { title: string; metrics: MetricRow[] }[] = [
    {
      title: "AI Performance",
      metrics: [
        { label: "Tokens/sec", key: "tps", value: cell.tps, unit: "T/s" },
        { label: "Time to First Token", key: "ttft", value: cell.ttft, unit: "ms" },
        { label: "Prompt Eval Time", key: "prompt_eval_time", value: cell.prompt_eval_time, unit: "ms" },
        { label: "Total Tokens", key: "total_tokens", value: cell.total_tokens, unit: "" },
        { label: "Stop Reason", key: "stop_reason", value: cell.stop_reason, unit: "" },
        { label: "RAM Delta", key: "ram_delta_mb", value: cell.ram_delta_mb, unit: "MB" },
        { label: "Load Duration", key: "load_duration", value: cell.load_duration, unit: "s" },
      ]
    },
    {
      title: "Hardware & Thermals",
      metrics: [
        { label: "CPU Peak Temp", key: "cpu_peak_temp", value: cell.cpu_peak_temp, unit: "°C" },
        { label: "Temp Delta", key: "temp_delta", value: cell.temp_delta, unit: "°C" },
        { label: "TDP", key: "tdp_watts", value: cell.tdp_watts, unit: "W" },
        { label: "Fan RPM", key: "fan_rpm", value: cell.fan_rpm, unit: "RPM" },
        { label: "Energy Cost", key: "energy_mwh", value: cell.energy_mwh, unit: "mWh" },
        { label: "Cooldown Velocity", key: "cooldown_vel", value: cell.cooldown_vel, unit: "°C/s" },
      ]
    },
    {
      title: "Article Metadata",
      metrics: [
        { label: "Compression Ratio", key: "comp_ratio", value: cell.comp_ratio, unit: ":1" },
        { label: "Flesch Score", key: "flesch_score", value: cell.flesch_score, unit: "" },
        { label: "AI Score", key: "ai_probability", value: cell.ai_probability, unit: "" },
        { label: "Duplicates", key: "dup_count", value: cell.dup_count, unit: "" },
        { label: "Dedup Latency", key: "dedup_lat", value: cell.dedup_lat, unit: "s" },
        { label: "TTL", key: "ttl_days", value: cell.ttl_days, unit: "days" },
      ]
    },
    {
      title: "Network & Source",
      metrics: [
        { label: "Fetch Latency", key: "fetch_lat", value: cell.fetch_lat, unit: "s" },
        { label: "Source Success", key: "src_success", value: cell.src_success, unit: "%" },
        { label: "Cloud Bypass", key: "cloud_bypass", value: cell.cloud_bypass, unit: "%" },
        { label: "Download Speed", key: "dl_kbps", value: cell.dl_kbps, unit: "kbps" },
      ]
    },
    {
      title: "Plugin Orchestration",
      metrics: [
        { label: "IPC Latency", key: "ipc_lat", value: cell.ipc_lat, unit: "s" },
        { label: "Press Duration", key: "press_dur", value: cell.press_dur, unit: "s" },
        { label: "UI FPS Drop", key: "ui_fps_drop", value: cell.ui_fps_drop, unit: "frames" },
      ]
    }
  ];

  const MODEL_NAMES: Record<string, string> = {
    "qwen2.5-0.5b": "Qwen2.5-0.5B",
    "mobilellm-600m": "MobileLLM-600M",
    "llama3.2-1b": "Llama 3.2-1B",
    "qwen3-0.6b": "Qwen3-0.6B",
  };

  const timestamp = new Date(cell.timestamp * 1000);
  const modelLabel = cell.model_id ? (MODEL_NAMES[cell.model_id] ?? cell.model_id) : cell.engine_type;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.85)',
        zIndex: 1000,
        padding: '32px 16px',
        overflowY: 'auto',
      }}
      onClick={onClose}
    >
      <Focusable
        style={{
          background: 'rgba(22, 26, 30, 0.98)',
          borderRadius: '8px',
          padding: '24px',
          maxWidth: '800px',
          margin: '0 auto',
          border: '1px solid rgba(61, 68, 80, 0.5)',
        }}
        onClick={(e: React.MouseEvent) => e.stopPropagation()}
      >
        <div style={{ marginBottom: '24px' }}>
          <h3 style={{ fontSize: '18px', color: '#e8eaed', marginBottom: '8px' }}>
            Session Metrics
          </h3>
          <div style={{ fontSize: '12px', color: '#8b8f98' }}>
            {timestamp.toLocaleString()} • {modelLabel}
          </div>
        </div>

        {sections.map((section, idx) => (
          <div key={idx} style={{ marginBottom: '24px' }}>
            <h4 style={{ fontSize: '14px', color: '#1a9fff', marginBottom: '12px', borderBottom: '1px solid rgba(61, 68, 80, 0.3)', paddingBottom: '6px' }}>
              {section.title}
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              {section.metrics.map((m, i) => {
                const valueColor = typeof m.value === 'number' && METRIC_THRESHOLDS[m.key]
                  ? getMetricColor(m.key, m.value) : '#e8eaed';
                return (
                <div key={i} style={{ padding: '10px', background: 'rgba(61, 68, 80, 0.2)', borderRadius: '4px', border: '1px solid rgba(61, 68, 80, 0.4)' }}>
                  <div style={{ fontSize: '10px', opacity: 0.7, color: '#8b8f98', marginBottom: '4px' }}>
                    {m.label}
                  </div>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: valueColor }}>
                    {formatValue(m.value, m.unit)}
                  </div>
                  {typeof m.value === 'number' && METRIC_THRESHOLDS[m.key] && (
                    <svg width="100%" height="3" style={{ display: 'block', marginTop: '4px' }}>
                      <rect x="0" y="0" width="100%" height="3" fill="rgba(61,68,80,0.4)" rx="1"/>
                      <rect x="0" y="0"
                        width={`${Math.min(100, (m.value / METRIC_THRESHOLDS[m.key].good[1]) * 100)}%`}
                        height="3" fill={valueColor} rx="1"/>
                    </svg>
                  )}
                </div>
              );})}
            </div>
          </div>
        ))}

        <Focusable
          style={{
            marginTop: '24px',
            padding: '12px',
            background: 'rgba(26, 159, 255, 0.15)',
            border: '1px solid rgba(26, 159, 255, 0.4)',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            color: '#1a9fff',
            fontSize: '14px',
          }}
          onActivate={onClose}
        >
          Close
        </Focusable>
      </Focusable>
    </div>
  );
};

const TelemetrySummaryStrip: FC = () => {
  const [stats, setStats] = useState<{ sessionCount: number; avgTps: number | null; peakTemp: number | null } | null>(null);

  useEffect(() => {
    getTelemetryHeatmap(48).then(result => {
      if (result.success && result.data && result.data.length > 0) {
        const d = result.data;
        const tpsValues = d.map(c => c.tps).filter((v): v is number => v !== null);
        const tempValues = d.map(c => c.cpu_peak_temp).filter((v): v is number => v !== null);
        setStats({
          sessionCount: d.length,
          avgTps: tpsValues.length > 0 ? tpsValues.reduce((a, b) => a + b, 0) / tpsValues.length : null,
          peakTemp: tempValues.length > 0 ? Math.max(...tempValues) : null,
        });
      } else {
        setStats({ sessionCount: 0, avgTps: null, peakTemp: null });
      }
    }).catch(() => setStats(null));
  }, []);

  if (!stats) return null;

  const tpsColor = stats.avgTps === null ? "#8b8f98" : stats.avgTps < 5 ? "#ffc82c" : "#4ade80";
  const tempColor = stats.peakTemp === null ? "#8b8f98" : stats.peakTemp > 80 ? "#d93936" : stats.peakTemp > 75 ? "#ffc82c" : "#4ade80";

  return (
    <div style={{ display: "flex", justifyContent: "space-around", padding: "10px 0", marginBottom: "8px" }}>
      {[
        { label: "sessions", value: stats.sessionCount.toString(), color: "#e8eaed" },
        { label: "T/s avg", value: stats.avgTps !== null ? `${stats.avgTps.toFixed(1)}` : "—", color: tpsColor },
        { label: "peak temp", value: stats.peakTemp !== null ? `${stats.peakTemp.toFixed(0)}°C` : "—", color: tempColor },
      ].map((stat, i) => (
        <div key={i} style={{ textAlign: "center" }}>
          <div style={{ fontSize: "13px", fontWeight: 600, color: stat.color }}>{stat.value}</div>
          <div style={{ fontSize: "10px", color: "#8b8f98", marginTop: "2px" }}>{stat.label}</div>
        </div>
      ))}
    </div>
  );
};

interface ForensicHeatmapProps {
  hours?: number;
  onClose: () => void;
}

const ForensicHeatmap: FC<ForensicHeatmapProps> = ({ hours = 6, onClose }) => {
  const [data, setData] = useState<HeatmapCell[]>([]);
  const [selectedCell, setSelectedCell] = useState<HeatmapCell | null>(null);
  const [colorBy, setColorBy] = useState<'tps' | 'temp'>('tps');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, [hours]);

  const loadData = async () => {
    setLoading(true);
    try {
      const result = await getTelemetryHeatmap(hours);
      if (result.success && result.data) {
        setData(result.data);
      } else {
        toaster.toast({
          title: "Telemetry Load Failed",
          body: result.error || "Could not load heatmap data"
        });
      }
    } catch (error) {
      console.error("Failed to load telemetry:", error);
    } finally {
      setLoading(false);
    }
  };

  const exportDossier = async () => {
    try {
      const result = await exportTelemetryDossier();
      if (result.success) {
        toaster.toast({
          title: "Dossier Exported",
          body: `Saved to ${result.path}`
        });
      } else {
        toaster.toast({
          title: "Export Failed",
          body: result.error || "Could not export dossier"
        });
      }
    } catch (error) {
      console.error("Failed to export dossier:", error);
    }
  };

  const clearData = async () => {
    if (!confirm("Clear all telemetry data? This cannot be undone.")) return;

    try {
      const result = await clearTelemetryData();
      if (result.success) {
        toaster.toast({ title: "Telemetry Cleared", body: "All data has been deleted" });
        loadData(); // Reload (should be empty now)
      }
    } catch (error) {
      console.error("Failed to clear telemetry:", error);
    }
  };

  const gridStyle: React.CSSProperties = {
    display: 'grid',
    gridTemplateColumns: 'repeat(12, 1fr)',
    gridTemplateRows: 'repeat(5, 60px)',
    gap: '4px',
    padding: '16px',
    maxWidth: '100%',
    overflowX: 'auto',
  };

  return (
    <div style={{ background: 'rgba(16, 20, 24, 0.98)', height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '16px', borderBottom: '1px solid #3d4450', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '20px', color: '#e8eaed', marginBottom: '4px' }}>
            Forensic Heatmap
          </h2>
          <div style={{ fontSize: '12px', color: '#8b8f98' }}>
            Last {hours} hours • {Math.min(data.length, 60)} sessions{data.length > 60 ? ` (of ${data.length})` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {(['tps', 'temp'] as const).map(mode => (
            <Focusable
              key={mode}
              style={{
                padding: '4px 10px',
                background: colorBy === mode ? 'rgba(26, 159, 255, 0.25)' : 'rgba(61, 68, 80, 0.3)',
                border: `1px solid ${colorBy === mode ? 'rgba(26, 159, 255, 0.6)' : 'rgba(61, 68, 80, 0.6)'}`,
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '11px',
                color: colorBy === mode ? '#1a9fff' : '#b8bcbf',
                transition: 'all 0.15s',
              }}
              onActivate={() => setColorBy(mode)}
            >
              {mode === 'tps' ? 'TPS' : 'Temp'}
            </Focusable>
          ))}
          <Focusable
            style={{
              padding: '8px 12px',
              background: 'rgba(61, 68, 80, 0.5)',
              border: '1px solid rgba(61, 68, 80, 0.8)',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '12px',
              color: '#b8bcbf',
            }}
            onActivate={onClose}
          >
            Close
          </Focusable>
        </div>
      </div>

      {/* Heatmap Grid */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#8b8f98' }}>
            <FaSpinner style={{ animation: 'spin 1s linear infinite', marginRight: '8px' }} />
            Loading telemetry...
          </div>
        ) : data.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100%', color: '#8b8f98' }}>
            <svg width="48" height="48" viewBox="0 0 48 48" style={{ marginBottom: '16px' }}>
              <rect x="4" y="28" width="10" height="16" fill="#8b8f98" opacity="0.3" rx="2"/>
              <rect x="19" y="18" width="10" height="26" fill="#8b8f98" opacity="0.3" rx="2"/>
              <rect x="34" y="8" width="10" height="36" fill="#8b8f98" opacity="0.3" rx="2"/>
            </svg>
            <div style={{ fontSize: '14px', marginBottom: '8px' }}>No Telemetry Data Yet</div>
            <div style={{ fontSize: '12px', opacity: 0.7 }}>
              AI summarization metrics will appear here
            </div>
          </div>
        ) : (
          <>
          <div style={gridStyle}>
            {data.slice(0, 60).map((cell) => (
              <HeatmapCell
                key={cell.id}
                data={cell}
                isFocused={false}
                colorBy={colorBy}
                onClick={() => setSelectedCell(cell)}
              />
            ))}
          </div>
          </>
        )}
      </div>

      {/* Actions Footer */}
      <div style={{ padding: '16px', borderTop: '1px solid #3d4450', display: 'flex', gap: '12px' }}>
        <Focusable
          style={{
            flex: 1,
            padding: '10px',
            background: 'rgba(26, 159, 255, 0.15)',
            border: '1px solid rgba(26, 159, 255, 0.4)',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            color: '#1a9fff',
            fontSize: '13px',
          }}
          onActivate={exportDossier}
        >
          Export Dossier
        </Focusable>
        <Focusable
          style={{
            flex: 1,
            padding: '10px',
            background: 'rgba(255, 59, 48, 0.15)',
            border: '1px solid rgba(255, 59, 48, 0.4)',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            color: '#ff3b30',
            fontSize: '13px',
          }}
          onActivate={clearData}
        >
          Clear Data
        </Focusable>
      </div>

      {/* Metric Inspector Modal */}
      {selectedCell && (
        <MetricInspector cell={selectedCell} onClose={() => setSelectedCell(null)} />
      )}
    </div>
  );
};

const QuickPeekCard: FC<QuickPeekCardProps> = ({ article, onClose }) => {
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
                if (!(window as any).openURL?.(article.link)) {
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

const ArticleCard: FC<ArticleCardProps> = ({
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
};

// Skeleton loader component
const SkeletonArticle: FC = () => {
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

interface NewsItemProps {
  article: NewsArticle;
  health: string;
  llmEnabled: boolean;
  llmStatus: LLMStatus | null;
  settings: Settings;
  index: number;
  onPageChange: (delta: number) => void;
}

const NewsItem: FC<NewsItemProps> = ({ article, health, llmEnabled, llmStatus, settings, index, onPageChange }) => {
  const [summary, setSummary] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [accentColor, setAccentColor] = useState<string>("#1a9fff");
  const [longPressTimer, setLongPressTimer] = useState<NodeJS.Timeout | null>(null);
  const [showHoverPreview, setShowHoverPreview] = useState(false);
  const [isLongPressing, setIsLongPressing] = useState(false);

  // Cleanup long-press timer on unmount
  useEffect(() => {
    return () => {
      if (longPressTimer) {
        clearTimeout(longPressTimer);
      }
    };
  }, [longPressTimer]);

  const handleClick = () => {
    // Prevent normal click if long-pressing
    if (isLongPressing) {
      setIsLongPressing(false);
      return;
    }
    const opened = window.open(article.link, "_blank");
    if (!opened) {
      if (!(window as any).openURL?.(article.link)) {
        toaster.toast({ title: "Open in browser", body: article.link });
      }
    }
  };

  const handlePointerDown = () => {
    if (!settings?.enableHoverPreview) return;

    const timer = setTimeout(() => {
      setIsLongPressing(true);
      setShowHoverPreview(true);
    }, settings.hoverPreviewDelay);

    setLongPressTimer(timer);
  };

  const handlePointerUp = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      setLongPressTimer(null);
    }

    // Close modal if long-pressing
    if (isLongPressing) {
      setShowHoverPreview(false);
      // Delay resetting isLongPressing to prevent handleClick from triggering
      setTimeout(() => setIsLongPressing(false), 100);
    }
  };

  const handlePointerLeave = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      setLongPressTimer(null);
    }
  };

  const handleSecondaryAction = () => {
    if (!settings?.enableHoverPreview) return;

    // Toggle preview modal
    setShowHoverPreview(!showHoverPreview);

    // Set up auto-dismiss timer (30 seconds)
    if (!showHoverPreview) {
      const timer = setTimeout(() => {
        setShowHoverPreview(false);
      }, 30000);
      setLongPressTimer(timer);
    } else {
      // Clear timer if closing
      if (longPressTimer) {
        clearTimeout(longPressTimer);
        setLongPressTimer(null);
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
        onButtonDown={(evt: GamepadEvent) => {
          if (evt.detail.button === GamepadButton.TRIGGER_LEFT) onPageChange(-1);
          else if (evt.detail.button === GamepadButton.TRIGGER_RIGHT) onPageChange(1);
        }}
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
              similarCount={5}
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
                    <span><FaSpinner style={{ animation: "spin 1s linear infinite" }} /> Summarizing...</span>
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
};

function Settings({ onBack }: { onBack?: () => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(false);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);
  const [showHeatmap, setShowHeatmap] = useState(false);

  // Named color constants
  const STATUS_GREEN = "#4ade80";
  const STATUS_YELLOW = "#ffc82c";
  const STATUS_RED = "#d93936";
  const COLOR_MUTED = "#8b8f98";
  const COLOR_ACCENT = "#1a9fff";

  // Debounce helper for slider inputs
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const debouncedUpdateSetting = (key: keyof Settings, value: any) => {
    if (debounceTimers.current[key]) clearTimeout(debounceTimers.current[key]);
    debounceTimers.current[key] = setTimeout(() => updateSetting(key, value), 400);
  };

  useEffect(() => {
    loadSettings();
    loadLLMStatus();
  }, []);

  const loadSettings = async () => {
    try {
      const loadedSettings = await getSettings();
      setSettings(loadedSettings);
    } catch (error) {
      console.error("Failed to load settings:", error);
    }
  };

  const loadLLMStatus = async () => {
    try {
      const status = await getLLMStatus();
      setLlmStatus(status);
    } catch (error) {
      console.error("Failed to load LLM status:", error);
    }
  };

  const updateSetting = async (key: keyof Settings, value: any) => {
    if (!settings) return;
    const prev = settings;

    setSettings({ ...settings, [key]: value });

    setLoading(true);
    try {
      await updateSettings({ [key]: value });
    } catch (error) {
      console.error("Failed to update settings:", error);
      toaster.toast({ title: "Settings error", body: "Failed to save — reverted" });
      setSettings(prev);
    } finally {
      setLoading(false);
    }
  };

  const toggleSource = async (source: string) => {
    if (!settings) return;
    const prev = settings;

    const currentSources = settings.sourcesEnabled || [];
    const newSources = currentSources.includes(source)
      ? currentSources.filter(s => s !== source)
      : [...currentSources, source];

    setSettings({ ...settings, sourcesEnabled: newSources });

    setLoading(true);
    try {
      await updateSettings({ sourcesEnabled: newSources });
    } catch (error) {
      console.error("Failed to update sources:", error);
      toaster.toast({ title: "Sources error", body: "Failed to save — reverted" });
      setSettings(prev);
    } finally {
      setLoading(false);
    }
  };

  if (!settings) {
    return (
      <PanelSection title="Settings">
        <PanelSectionRow>
          <div style={{ textAlign: "center", padding: "20px", color: "#8b8f98" }}>
            Loading settings...
          </div>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const sources = ["IGN", "PCGamer", "Steam", "Kotaku", "GameSpot", "Polygon"];

  return (
    <div style={{ marginTop: "16px" }}>
      <PanelSection title="News Sources">
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: "#8b8f98", marginBottom: "8px" }}>
            Select which gaming news sources to display
          </div>
        </PanelSectionRow>
        {sources.map((source) => (
          <PanelSectionRow key={source}>
            <ToggleField
              label={source}
              checked={settings.sourcesEnabled?.includes(source) ?? false}
              onChange={() => toggleSource(source)}
              disabled={loading}
            />
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title="Refresh Settings">
        <PanelSectionRow>
          <SliderField
            label="Refresh Interval"
            value={settings.refreshInterval || 30}
            min={5}
            max={120}
            step={5}
            onChange={(value) => debouncedUpdateSetting("refreshInterval", value)}
            disabled={loading}
            bottomSeparator="none"
          />
          <div style={{ fontSize: "12px", color: "#8b8f98", marginTop: "4px" }}>
            Automatically refresh news every {settings.refreshInterval || 30} minutes
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="AI Summaries">
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: "#8b8f98", marginBottom: "8px" }}>
            Generate AI-powered article summaries on your Steam Deck
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Enable AI Summaries"
            description={
              llmStatus?.model_downloaded
                ? "Summarize articles with local AI"
                : `Downloads ~${llmStatus?.model_size_mb ?? 352}MB model on first use`
            }
            checked={settings.llmEnabled ?? false}
            onChange={async (value) => {
              if (value && !llmStatus?.model_downloaded) {
                // Need to download model first
                setDownloadingModel(true);
                toaster.toast({
                  title: "Downloading AI Model",
                  body: "This may take a few minutes..."
                });
                try {
                  const result = await downloadLLMModel();
                  if (result.success) {
                    await updateSetting("llmEnabled", true);
                    setLlmStatus(result.status);
                    toaster.toast({
                      title: "AI Ready",
                      body: "You can now summarize articles!"
                    });
                  } else {
                    toaster.toast({
                      title: "Download Failed",
                      body: result.error || "Please try again"
                    });
                  }
                } catch (error) {
                  console.error("Model download failed:", error);
                  toaster.toast({
                    title: "Download Failed",
                    body: "Please check your connection"
                  });
                } finally {
                  setDownloadingModel(false);
                }
              } else {
                await updateSetting("llmEnabled", value);
                if (!value && llmStatus?.model_loaded) {
                  // Unload model to free memory
                  await unloadLLMModel();
                  await loadLLMStatus();
                }
              }
            }}
            disabled={loading || downloadingModel}
          />
        </PanelSectionRow>

        {/* Configuration - always visible */}
        <PanelSectionRow>
          <DropdownItem
            label="AI Model"
            description="Select which model to use for summaries"
            rgOptions={[
              { data: "qwen2.5-0.5b", label: "Qwen2.5-0.5B (Default, 352MB)" },
              { data: "mobilellm-600m", label: "MobileLLM-600M ⚠ Experimental (430MB)" },
              { data: "llama3.2-1b", label: "Llama 3.2-1B (700MB)" },
              { data: "qwen3-0.6b", label: "Qwen3-0.6B (400MB)" },
            ]}
            selectedOption={settings?.selectedModel ?? "qwen2.5-0.5b"}
            onChange={async (option: SingleDropdownOption) => {
              await updateSetting("selectedModel", option.data);
              await loadLLMStatus();
            }}
          />
        </PanelSectionRow>

        {(settings?.selectedModel === "mobilellm-600m") && (
          <PanelSectionRow>
            <div style={{ padding: "8px 10px", background: "rgba(255, 180, 0, 0.1)", borderRadius: "6px", fontSize: "11px", color: "#ffb400", lineHeight: "1.4" }}>
              <strong>Experimental model</strong> — MobileLLM-600M is a base model without instruction tuning. Summary quality will be lower and less consistent than Qwen2.5-0.5B.
            </div>
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <DropdownItem
            label="AI Personality"
            description="Writing style for summaries"
            rgOptions={[
              { data: "analyst", label: "Analyst (Default)" },
              { data: "tldr", label: "TLDR (Ultra-Concise)" }
            ]}
            selectedOption={settings?.aiPersonality ?? "analyst"}
            onChange={(option: SingleDropdownOption) => updateSetting("aiPersonality", option.data)}
          />
        </PanelSectionRow>

        {/* Operational settings - only when enabled */}
        {settings.llmEnabled && (
          <>
            <PanelSectionRow>
              <SliderField
                label="Summarization Cooldown"
                value={settings.llmCooldownSeconds ?? 20}
                min={5}
                max={120}
                step={5}
                onChange={(value) => debouncedUpdateSetting("llmCooldownSeconds", value)}
                bottomSeparator="none"
                description={`Wait ${settings.llmCooldownSeconds ?? 20}s between summaries to prevent thermal issues`}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label="Allow AI During Gaming"
                description="Enable LLM summarization while games are running (may impact performance)"
                checked={settings?.allowLlmDuringGaming ?? false}
                onChange={async (value) => {
                  if (value) {
                    const confirmed = window.confirm(
                      "Performance Warning\n\n" +
                      "Enabling AI summarization during gaming may cause:\n" +
                      "• Reduced game FPS\n" +
                      "• Increased CPU temperature\n" +
                      "• Higher battery drain\n\n" +
                      "Recommended: Keep this OFF unless you have excess system resources.\n\n" +
                      "Enable anyway?"
                    );
                    if (confirmed) {
                      await updateSetting("allowLlmDuringGaming", true);
                    }
                  } else {
                    await updateSetting("allowLlmDuringGaming", false);
                  }
                }}
                disabled={loading}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <SliderField
                label="Temp Ceiling"
                value={settings.llmTempCeilingCelsius ?? 75}
                min={50}
                max={95}
                step={5}
                onChange={(value) => debouncedUpdateSetting("llmTempCeilingCelsius", value)}
                bottomSeparator="none"
                description={`Block inference above ${settings.llmTempCeilingCelsius ?? 75}°C`}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <SliderField
                label="Thermal Bonus Cooldown"
                value={settings.llmThermalCooldownBonus ?? 30}
                min={0}
                max={120}
                step={10}
                onChange={(value) => debouncedUpdateSetting("llmThermalCooldownBonus", value)}
                bottomSeparator="none"
                description={`Extra ${settings.llmThermalCooldownBonus ?? 30}s after hot inference`}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label="Adaptive Tokens"
                description="Reduce output length when CPU is hot"
                checked={settings?.llmAdaptiveTokens ?? true}
                onChange={(value) => updateSetting("llmAdaptiveTokens", value)}
                disabled={loading}
              />
            </PanelSectionRow>

            {(settings?.llmAdaptiveTokens ?? true) && (
              <PanelSectionRow>
                <SliderField
                  label="Reduced Token Count"
                  value={settings.llmReducedTokenCount ?? 80}
                  min={40}
                  max={150}
                  step={10}
                  onChange={(value) => debouncedUpdateSetting("llmReducedTokenCount", value)}
                  bottomSeparator="none"
                  description={`${settings.llmReducedTokenCount ?? 80} tokens when throttling (normal: 150)`}
                />
              </PanelSectionRow>
            )}

            <PanelSectionRow>
              <ToggleField
                label="Adaptive Threads"
                description="Reduce to 1 thread during gaming or when hot"
                checked={settings?.llmAdaptiveThreads ?? true}
                onChange={(value) => updateSetting("llmAdaptiveThreads", value)}
                disabled={loading}
              />
            </PanelSectionRow>

            {/* Model Status Card */}
            <PanelSectionRow>
              <div style={{ padding: "10px", background: "rgba(26, 159, 255, 0.08)", borderRadius: "6px", fontSize: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                  <span style={{ color: "#8b8f98" }}>Model</span>
                  <span style={{ color: "#c8cdd8", fontSize: "11px" }}>
                    {llmStatus?.model_display_name ?? "Qwen2.5-0.5B"}
                    {llmStatus?.experimental && (
                      <span style={{ marginLeft: "4px", color: "#ffb400", fontSize: "10px" }}>⚠</span>
                    )}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                  <span style={{ color: "#8b8f98" }}>Status</span>
                  <span style={{ color: llmStatus?.model_loaded ? STATUS_GREEN : llmStatus?.model_downloaded ? STATUS_YELLOW : COLOR_MUTED }}>
                    {llmStatus?.model_loaded ? "Loaded" : llmStatus?.model_downloaded ? "Ready" : "Not Downloaded"}
                  </span>
                </div>

                {/* Resource monitoring when available */}
                {(llmStatus?.rate_limiter?.cooldown_remaining_seconds ?? 0) > 0 && (
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                    <span style={{ color: "#8b8f98" }}>Cooldown</span>
                    <span style={{ color: STATUS_YELLOW }}>
                      {Math.ceil(llmStatus?.rate_limiter?.cooldown_remaining_seconds ?? 0)}s
                    </span>
                  </div>
                )}
                {llmStatus?.resources && (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: "#8b8f98" }}>Memory Available</span>
                      <span style={{ color: llmStatus.resources.can_proceed ? STATUS_GREEN : STATUS_RED }}>
                        {Math.round(llmStatus.resources.memory_available_mb)}MB
                      </span>
                    </div>
                    {llmStatus.resources.cpu_temp_celsius && (
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "4px" }}>
                        <span style={{ color: "#8b8f98" }}>CPU Temp</span>
                        <span style={{ color: llmStatus.resources.cpu_temp_celsius > 80 ? STATUS_RED : STATUS_GREEN }}>
                          {Math.round(llmStatus.resources.cpu_temp_celsius)}°C
                        </span>
                      </div>
                    )}
                  </>
                )}

                {/* Download button when not downloaded */}
                {!llmStatus?.model_downloaded && !downloadingModel && (
                  <button
                    onClick={async () => {
                      setDownloadingModel(true);
                      try {
                        const result = await downloadLLMModel();
                        if (result.success) {
                          await loadLLMStatus();
                          toaster.toast({ title: "Model Ready", body: "AI summarization enabled!" });
                        } else {
                          toaster.toast({ title: "Download Failed", body: result.error || "Please try again" });
                        }
                      } finally {
                        setDownloadingModel(false);
                      }
                    }}
                    style={{ width: "100%", padding: "6px 8px", fontSize: "11px", background: "rgba(26, 159, 255, 0.2)", border: "1px solid #1a9fff", borderRadius: "4px", cursor: "pointer", color: "#1a9fff", transition: "all 0.2s", marginTop: "8px" }}
                  >
                    Download Model (~350MB)
                  </button>
                )}

                {/* Downloading indicator */}
                {downloadingModel && (
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "4px", marginTop: "8px" }}>
                    <FaSpinner style={{ animation: "spin 1s linear infinite", color: "#1a9fff" }} />
                    <span style={{ fontSize: "11px", color: "#8b8f98" }}>Downloading...</span>
                  </div>
                )}

                {/* Management buttons when downloaded */}
                {llmStatus?.model_downloaded && (
                  <div style={{ display: "flex", gap: "6px", marginTop: "8px" }}>
                    <button
                      onClick={async () => {
                        try {
                          if (llmStatus.model_loaded) await unloadLLMModel();
                          const success = await deleteLLMModel();
                          if (success) {
                            await loadLLMStatus();
                            await updateSetting("llmEnabled", false);
                            toaster.toast({ title: "Model Deleted", body: "AI model has been removed" });
                          }
                        } catch (error) {
                          console.error("Delete failed:", error);
                        }
                      }}
                      disabled={downloadingModel}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        flex: 1,
                        padding: "4px 8px",
                        fontSize: "11px",
                        background: "rgba(255, 59, 48, 0.1)",
                        border: "1px solid rgba(255, 59, 48, 0.3)",
                        borderRadius: "4px",
                        color: "#ff3b30",
                        cursor: downloadingModel ? "not-allowed" : "pointer",
                        opacity: downloadingModel ? 0.5 : 1,
                        transition: "all 0.2s"
                      }}
                    >
                      <FaTrash style={{ fontSize: "10px" }} />
                      Delete
                    </button>
                    <button
                      onClick={async () => {
                        setDownloadingModel(true);
                        try {
                          if (llmStatus.model_loaded) await unloadLLMModel();
                          await deleteLLMModel();
                          const result = await downloadLLMModel();
                          if (result.success) {
                            setLlmStatus(result.status);
                            toaster.toast({ title: "Model Redownloaded", body: "AI model is ready" });
                          } else {
                            toaster.toast({ title: "Download Failed", body: result.error || "Please try again" });
                          }
                        } catch (error) {
                          console.error("Redownload failed:", error);
                        } finally {
                          setDownloadingModel(false);
                          await loadLLMStatus();
                        }
                      }}
                      disabled={downloadingModel}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "4px",
                        flex: 1,
                        padding: "4px 8px",
                        fontSize: "11px",
                        background: "rgba(26, 159, 255, 0.1)",
                        border: "1px solid rgba(26, 159, 255, 0.3)",
                        borderRadius: "4px",
                        color: "#1a9fff",
                        cursor: downloadingModel ? "not-allowed" : "pointer",
                        opacity: downloadingModel ? 0.5 : 1,
                        transition: "all 0.2s"
                      }}
                    >
                      <FaDownload style={{ fontSize: "10px" }} />
                      Redownload
                    </button>
                  </div>
                )}
              </div>
            </PanelSectionRow>

            {/* Circuit breaker warning */}
            {llmStatus?.circuit_breaker?.state === "open" && (
              <PanelSectionRow>
                <div style={{ padding: "8px", background: "rgba(217, 57, 54, 0.1)", borderRadius: "4px", fontSize: "12px", color: STATUS_RED }}>
                  AI temporarily disabled due to errors. Will retry automatically.
                </div>
              </PanelSectionRow>
            )}
          </>
        )}


      </PanelSection>

      <PanelSection title="Interaction Features">
        <PanelSectionRow>
          <ToggleField
            label="Long-Press Preview"
            description="Hold article to show quick preview"
            checked={settings?.enableHoverPreview ?? true}
            onChange={(value) => updateSetting("enableHoverPreview", value)}
          />
        </PanelSectionRow>

        {settings?.enableHoverPreview && (
          <PanelSectionRow>
            <SliderField
              label="Preview Delay"
              value={settings?.hoverPreviewDelay ?? 500}
              min={200}
              max={1000}
              step={100}
              onChange={(value) => debouncedUpdateSetting("hoverPreviewDelay", value)}
              bottomSeparator="none"
              description={`${settings?.hoverPreviewDelay ?? 500}ms hold time`}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Appearance">
        <PanelSectionRow>
          <DropdownItem
            label="View Mode"
            rgOptions={[
              { data: "compact", label: "Compact" },
              { data: "comfortable", label: "Comfortable (Default)" },
              { data: "magazine", label: "Magazine" }
            ]}
            selectedOption={settings?.uiViewMode ?? "comfortable"}
            onChange={(option: SingleDropdownOption) => updateSetting("uiViewMode", option.data)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Show Source Icons"
            description="Display favicons next to source names"
            checked={settings?.showSourceIcons ?? true}
            onChange={(value) => updateSetting("showSourceIcons", value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <SliderField
            label="Glass Effect Intensity"
            value={settings?.glassmorphismOpacity ?? 30}
            min={0}
            max={100}
            step={10}
            onChange={(value) => debouncedUpdateSetting("glassmorphismOpacity", value)}
            bottomSeparator="none"
            description="Card background blur (higher = more blur)"
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Automatic Accent Colors"
            description="Extract colors from source logos"
            checked={settings?.accentColorSource === "automatic"}
            onChange={(value) => updateSetting("accentColorSource", value ? "automatic" : "default")}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="Dynamic Backdrops"
            description="Show blurred image on focused articles"
            checked={settings?.dynamicBackdropEnabled ?? true}
            onChange={(value) => updateSetting("dynamicBackdropEnabled", value)}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <ToggleField
            label="AI Typewriter Effect"
            description="Animate summary text reveal"
            checked={settings?.aiTypewriterEnabled ?? true}
            onChange={(value) => updateSetting("aiTypewriterEnabled", value)}
          />
        </PanelSectionRow>

        {settings?.aiTypewriterEnabled && (
          <PanelSectionRow>
            <SliderField
              label="Typewriter Speed"
              value={settings?.aiTypewriterSpeed ?? 30}
              min={10}
              max={100}
              step={10}
              onChange={(value) => debouncedUpdateSetting("aiTypewriterSpeed", value)}
              bottomSeparator="none"
              description={`${settings?.aiTypewriterSpeed ?? 30} characters/second`}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      <div style={{ margin: "8px 16px", borderTop: "1px solid #3d4450", opacity: 0.5 }} />

      <PanelSection title="Telemetry">
        <PanelSectionRow>
          <TelemetrySummaryStrip />
        </PanelSectionRow>
        <PanelSectionRow>
          <Focusable
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px",
              padding: "10px 16px",
              background: "linear-gradient(135deg, rgba(26, 159, 255, 0.15) 0%, rgba(26, 159, 255, 0.05) 100%)",
              border: "1px solid rgba(26, 159, 255, 0.3)",
              borderRadius: "6px",
              cursor: "pointer",
              transition: "all 0.2s",
              fontSize: "13px",
              color: COLOR_ACCENT
            }}
            onActivate={() => setShowHeatmap(true)}
          >
            <span>View Forensic Heatmap</span>
          </Focusable>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection>
        <PanelSectionRow>
          <ToggleField
            label="Debug Mode"
            description="Enable detailed logging for troubleshooting"
            checked={settings.debugMode ?? false}
            onChange={(value) => updateSetting("debugMode", value)}
            disabled={loading}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <button
            onClick={() => {
              if (onBack) {
                onBack();
              }
            }}
            style={{
              width: "100%",
              padding: "8px",
              fontSize: "12px",
              background: "rgba(255, 255, 255, 0.05)",
              border: "1px solid rgba(255, 255, 255, 0.1)",
              borderRadius: "4px",
              color: COLOR_MUTED,
              cursor: "pointer",
              transition: "all 0.2s"
            }}
          >
            Back to News
          </button>
        </PanelSectionRow>
      </PanelSection>

      {/* Forensic Heatmap Modal */}
      {showHeatmap && (
        <ForensicHeatmap
          hours={6}
          onClose={() => setShowHeatmap(false)}
        />
      )}
    </div>
  );
}

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
    const input = (window as any).SteamClient?.Input;
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
    return <Settings onBack={onBackToNews} />;
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
                key={`${article.source}-${idx}`}
                article={article}
                health={sourceHealth[article.source] || 'ok'}
                llmEnabled={llmStatus?.enabled ?? false}
                llmStatus={llmStatus}
                settings={settings || {
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
                }}
                index={idx}
                onPageChange={(delta) => {
                  if (delta < 0 && page > 1 && !loading) loadNews(page - 1, true);
                  else if (delta > 0 && page < totalPages && !loading) loadNews(page + 1, true);
                }}
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
                  onActivate={() => page > 1 && !loading && loadNews(page - 1, true)}
                  onClick={() => page > 1 && !loading && loadNews(page - 1, true)}
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
                  onActivate={() => page < totalPages && !loading && loadNews(page + 1, true)}
                  onClick={() => page < totalPages && !loading && loadNews(page + 1, true)}
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

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </Focusable>
  );
}

// State management for settings toggle
let setShowSettingsGlobal: ((show: boolean) => void) | null = null;

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
            onActivate={async () => {
              await refreshNews();
              toaster.toast({
                title: "Refreshing",
                body: "Fetching latest news..."
              });
            }}
            onClick={async () => {
              await refreshNews();
              toaster.toast({
                title: "Refreshing",
                body: "Fetching latest news..."
              });
            }}
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
