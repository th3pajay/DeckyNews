import { callable } from "@decky/api";
import {
  NewsFeedResponse,
  Settings,
  SourceHealth,
  SummarizeResponse,
  LLMStatus,
  DownloadResponse,
  SparklineData,
  TelemetryHeatmapResponse,
  ExportDossierResponse,
} from "./types";

export const getNews = callable<[page: number, items_per_page: number], NewsFeedResponse>("get_news");
export const refreshNews = callable<[], boolean>("refresh_news");
export const getSourceHealth = callable<[], SourceHealth>("get_source_health");
export const getSettings = callable<[], Settings>("get_settings");
export const updateSettings = callable<[settings: Partial<Settings>], boolean>("update_settings");

export const summarizeArticle = callable<[url: string, title: string], SummarizeResponse>("summarize_article");
export const getLLMStatus = callable<[], LLMStatus>("get_llm_status");
export const downloadLLMModel = callable<[], DownloadResponse>("download_llm_model");
export const unloadLLMModel = callable<[], boolean>("unload_llm_model");
export const deleteLLMModel = callable<[], boolean>("delete_llm_model");

export const getCoverageSparkline = callable<[hash: string], SparklineData>("get_coverage_sparkline");

export const getTelemetryHeatmap = callable<[hours: number], TelemetryHeatmapResponse>("get_telemetry_heatmap");
export const exportTelemetryDossier = callable<[], ExportDossierResponse>("export_telemetry_dossier");
export const clearTelemetryData = callable<[], { success: boolean }>("clear_telemetry_data");
