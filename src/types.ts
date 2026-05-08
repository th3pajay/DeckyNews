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

export interface LLMStatus {
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

export interface LoadDiagnostics {
  model_path: string;
  model_exists: boolean;
  model_size_bytes: number;
  binary_path: string | null;
  binary_exists: boolean;
  binary_candidates_checked: Record<string, BinaryCandidateStatus>;
  plugin_dir: string;
  runtime_dir: string;
}

export interface SummarizeResponse {
  success: boolean;
  summary: string | null;
  error: string | null;
  status: LLMStatus | null;
  diagnostics?: LoadDiagnostics;
}

export interface DownloadResponse {
  success: boolean;
  error?: string;
  status: LLMStatus;
}

export interface NewsArticle {
  title: string;
  link: string;
  published: string;
  source: string;
  content?: string;
  image_url?: string;
  favicon_url?: string;
  similarity_hash?: string;
}

export interface SparklinePoint {
  hour: string;
  count: number;
  normalized: number;
}

export interface SparklineData {
  points: SparklinePoint[];
  max_count: number;
}

export interface HeatmapCell {
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

export interface TelemetryHeatmapResponse {
  success: boolean;
  data?: HeatmapCell[];
  error?: string;
}

export interface ExportDossierResponse {
  success: boolean;
  path?: string;
  error?: string;
}

export interface NewsFeedResponse {
  articles: NewsArticle[];
  total: number;
  page: number;
  totalPages: number;
}

export interface Settings {
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

export interface SourceHealth {
  [key: string]: "ok" | "warning" | "error";
}

export interface QuickPeekCardProps {
  article: NewsArticle;
  onClose: () => void;
}
