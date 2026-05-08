import { useState, useEffect, useRef } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ToggleField,
  SliderField,
  DropdownItem,
  SingleDropdownOption,
  Focusable,
} from "@decky/ui";
import { toaster } from "@decky/api";
import { FaTrash, FaDownload } from "react-icons/fa";
import {
  getSettings,
  updateSettings,
  getLLMStatus,
  downloadLLMModel,
  unloadLLMModel,
  deleteLLMModel,
} from "../api";
import { Settings as SettingsType, LLMStatus, DownloadResponse } from "../types";
import { TelemetrySummaryStrip, ForensicHeatmap } from "./Telemetry";

// Suppress unused import warning — used as type reference
void ({} as DownloadResponse);

export function Settings(_props: { onBack?: () => void }) {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [loading, setLoading] = useState(false);
  const [llmStatus, setLlmStatus] = useState<LLMStatus | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [selectedPage, setSelectedPage] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);

  // Named color constants
  const STATUS_GREEN = "#4ade80";
  const STATUS_YELLOW = "#ffc82c";
  const STATUS_RED = "#d93936";
  const COLOR_MUTED = "#8b8f98";
  const COLOR_ACCENT = "#1a9fff";

  // Debounce helper for slider inputs
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const debouncedUpdateSetting = (key: keyof SettingsType, value: any) => {
    if (debounceTimers.current[key]) clearTimeout(debounceTimers.current[key]);
    debounceTimers.current[key] = setTimeout(() => updateSetting(key, value), 400);
  };

  useEffect(() => {
    Promise.all([loadSettings(), loadLLMStatus()]);
  }, []);

  // Poll backend for download_progress while a download is in flight
  useEffect(() => {
    if (!downloadingModel) return;
    const id = setInterval(async () => {
      try {
        const status = await getLLMStatus();
        setLlmStatus(status);
        setDownloadProgress(status.download_progress ?? 0);
      } catch {}
    }, 1000);
    return () => clearInterval(id);
  }, [downloadingModel]);

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

  const updateSetting = async (key: keyof SettingsType, value: any) => {
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
  const PAGE_TITLES = ["Sources", "Feed", "AI", "AI Perf", "Display", "Advanced"];

  return (
    <div>
      <PanelSection>
        <PanelSectionRow>
          <Focusable
            style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", padding: "2px 0" }}
            onActivate={() => setMenuOpen(!menuOpen)}
          >
            <span style={{ fontWeight: 600, fontSize: "13px" }}>{PAGE_TITLES[selectedPage]}</span>
            <span style={{ color: "#8b8f98", fontSize: "12px" }}>{menuOpen ? "▲" : "▼"}</span>
          </Focusable>
        </PanelSectionRow>
        {menuOpen && PAGE_TITLES.map((title, i) => (
          <PanelSectionRow key={title}>
            <Focusable
              style={{ cursor: "pointer", padding: "4px 0", fontWeight: i === selectedPage ? 600 : 400, color: i === selectedPage ? "#1a9fff" : "inherit", fontSize: "13px" }}
              onActivate={() => { setSelectedPage(i); setMenuOpen(false); }}
            >
              {title}
            </Focusable>
          </PanelSectionRow>
        ))}
      </PanelSection>
      {selectedPage === 0 && (
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
            )}
      {selectedPage === 1 && (
              <PanelSection title="Feed">
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
                <PanelSectionRow>
                  <SliderField
                    label="Article Retention"
                    value={settings.articleRetention ?? 500}
                    min={100}
                    max={2000}
                    step={100}
                    onChange={(value) => debouncedUpdateSetting("articleRetention", value)}
                    bottomSeparator="none"
                    description={`Keep up to ${settings.articleRetention ?? 500} articles in the database`}
                  />
                </PanelSectionRow>
              </PanelSection>
            )}
      {selectedPage === 2 && (
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
                          await unloadLLMModel();
                          await loadLLMStatus();
                        }
                      }
                    }}
                    disabled={loading || downloadingModel}
                  />
                </PanelSectionRow>

                <PanelSectionRow>
                  <DropdownItem
                    label="AI Model"
                    description="Select which model to use for summaries"
                    rgOptions={[
                      { data: "qwen2.5-0.5b", label: "Qwen2.5-0.5B (Default, 352MB)" },
                      { data: "mobilellm-600m", label: "MobileLLM-600M ⚠ Experimental (430MB)" },
                      { data: "llama3.2-1b", label: "Llama 3.2-1B (700MB)" },
                      { data: "qwen3-0.6b-thinking", label: "Qwen3-0.6B Thinking (~400MB)" },
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

                {settings.llmEnabled && (
                  <>
                    <PanelSectionRow>
                      <div style={{ padding: "12px", background: "rgba(255,255,255,0.04)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.08)", fontSize: "12px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "10px" }}>
                          <div>
                            <div style={{ fontSize: "12px", fontWeight: 600, color: "#c8cdd8" }}>
                              {llmStatus?.model_display_name ?? "Qwen2.5-0.5B"}
                              {llmStatus?.experimental && (
                                <span style={{ marginLeft: "6px", fontSize: "10px", color: "#ffb400" }}>⚠ Experimental</span>
                              )}
                            </div>
                            <div style={{ fontSize: "10px", color: COLOR_MUTED, marginTop: "2px" }}>
                              {llmStatus?.model_size_mb ?? 352}MB · {settings?.selectedModel ?? "qwen2.5-0.5b"}
                            </div>
                          </div>
                          <div style={{
                            padding: "2px 8px",
                            borderRadius: "12px",
                            fontSize: "10px",
                            fontWeight: 600,
                            background: llmStatus?.model_loaded
                              ? "rgba(74,222,128,0.15)"
                              : llmStatus?.model_downloaded
                              ? "rgba(255,200,44,0.15)"
                              : "rgba(139,143,152,0.12)",
                            color: llmStatus?.model_loaded ? STATUS_GREEN : llmStatus?.model_downloaded ? STATUS_YELLOW : COLOR_MUTED,
                            border: `1px solid ${llmStatus?.model_loaded ? "rgba(74,222,128,0.3)" : llmStatus?.model_downloaded ? "rgba(255,200,44,0.3)" : "rgba(139,143,152,0.2)"}`,
                          }}>
                            {llmStatus?.model_loaded ? "● Loaded" : llmStatus?.model_downloaded ? "● Ready" : "○ Not Downloaded"}
                          </div>
                        </div>

                        {downloadingModel && (
                          <div style={{ marginBottom: "10px" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "5px" }}>
                              <span style={{ fontSize: "10px", color: COLOR_MUTED }}>Downloading…</span>
                              <span style={{ fontSize: "10px", color: COLOR_ACCENT, fontWeight: 600 }}>
                                {Math.round(downloadProgress)}%
                              </span>
                            </div>
                            <div style={{ height: "6px", background: "rgba(255,255,255,0.08)", borderRadius: "3px", overflow: "hidden" }}>
                              <div style={{
                                height: "100%",
                                width: `${downloadProgress}%`,
                                background: "linear-gradient(90deg, #1a9fff, #56c7ff)",
                                borderRadius: "3px",
                                transition: "width 0.5s ease",
                                minWidth: downloadProgress > 0 ? "6px" : "0",
                              }} />
                            </div>
                            <div style={{ fontSize: "10px", color: COLOR_MUTED, marginTop: "3px" }}>
                              {Math.round((downloadProgress / 100) * (llmStatus?.model_size_mb ?? 352))}MB / {llmStatus?.model_size_mb ?? 352}MB
                            </div>
                          </div>
                        )}

                        {!downloadingModel && llmStatus?.resources && (
                          <div style={{ display: "flex", gap: "6px", marginBottom: "10px" }}>
                            <div style={{ flex: 1, padding: "5px 8px", background: "rgba(255,255,255,0.03)", borderRadius: "5px" }}>
                              <div style={{ fontSize: "9px", color: COLOR_MUTED, marginBottom: "1px" }}>RAM Free</div>
                              <div style={{ fontSize: "11px", fontWeight: 600, color: llmStatus.resources.can_proceed ? STATUS_GREEN : STATUS_RED }}>
                                {Math.round(llmStatus.resources.memory_available_mb)}MB
                              </div>
                            </div>
                            {llmStatus.resources.cpu_temp_celsius != null && (
                              <div style={{ flex: 1, padding: "5px 8px", background: "rgba(255,255,255,0.03)", borderRadius: "5px" }}>
                                <div style={{ fontSize: "9px", color: COLOR_MUTED, marginBottom: "1px" }}>CPU Temp</div>
                                <div style={{ fontSize: "11px", fontWeight: 600, color: llmStatus.resources.cpu_temp_celsius > 80 ? STATUS_RED : STATUS_GREEN }}>
                                  {Math.round(llmStatus.resources.cpu_temp_celsius)}°C
                                </div>
                              </div>
                            )}
                            {(llmStatus.rate_limiter?.cooldown_remaining_seconds ?? 0) > 0 && (
                              <div style={{ flex: 1, padding: "5px 8px", background: "rgba(255,255,255,0.03)", borderRadius: "5px" }}>
                                <div style={{ fontSize: "9px", color: COLOR_MUTED, marginBottom: "1px" }}>Cooldown</div>
                                <div style={{ fontSize: "11px", fontWeight: 600, color: STATUS_YELLOW }}>
                                  {Math.ceil(llmStatus.rate_limiter.cooldown_remaining_seconds)}s
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        {!downloadingModel && !llmStatus?.model_downloaded && (
                          <button
                            onClick={async () => {
                              setDownloadProgress(0);
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
                                setDownloadProgress(0);
                              }
                            }}
                            style={{ width: "100%", padding: "7px", fontSize: "11px", fontWeight: 600, background: "rgba(26,159,255,0.15)", border: "1px solid rgba(26,159,255,0.4)", borderRadius: "5px", cursor: "pointer", color: COLOR_ACCENT }}
                          >
                            ↓ Download Model ({llmStatus?.model_size_mb ?? 352}MB)
                          </button>
                        )}

                        {!downloadingModel && llmStatus?.model_downloaded && (
                          <div style={{ display: "flex", gap: "6px" }}>
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
                              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "4px", padding: "6px", fontSize: "11px", background: "rgba(217,57,54,0.1)", border: "1px solid rgba(217,57,54,0.3)", borderRadius: "5px", color: STATUS_RED, cursor: "pointer" }}
                            >
                              <FaTrash style={{ fontSize: "10px" }} /> Delete
                            </button>
                            <button
                              onClick={async () => {
                                setDownloadProgress(0);
                                setDownloadingModel(true);
                                try {
                                  if (llmStatus.model_loaded) await unloadLLMModel();
                                  await deleteLLMModel();
                                  const result = await downloadLLMModel();
                                  if (result.success) {
                                    setLlmStatus(result.status);
                                    toaster.toast({ title: "Model Updated", body: "AI model is ready" });
                                  } else {
                                    toaster.toast({ title: "Download Failed", body: result.error || "Please try again" });
                                  }
                                } catch (error) {
                                  console.error("Redownload failed:", error);
                                } finally {
                                  setDownloadingModel(false);
                                  setDownloadProgress(0);
                                  await loadLLMStatus();
                                }
                              }}
                              style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "4px", padding: "6px", fontSize: "11px", background: "rgba(26,159,255,0.1)", border: "1px solid rgba(26,159,255,0.3)", borderRadius: "5px", color: COLOR_ACCENT, cursor: "pointer" }}
                            >
                              <FaDownload style={{ fontSize: "10px" }} /> Redownload
                            </button>
                          </div>
                        )}
                      </div>
                    </PanelSectionRow>

                    {llmStatus?.circuit_breaker?.state === "open" && (
                      <PanelSectionRow>
                        <div style={{ padding: "8px", background: "rgba(217,57,54,0.1)", borderRadius: "4px", fontSize: "12px", color: STATUS_RED }}>
                          AI temporarily disabled due to errors. Will retry automatically.
                        </div>
                      </PanelSectionRow>
                    )}
                  </>
                )}
              </PanelSection>
            )}
      {selectedPage === 3 && (!settings.llmEnabled ? (
              <PanelSection title="AI Performance">
                <PanelSectionRow>
                  <div style={{ fontSize: "12px", color: "#8b8f98", padding: "8px 0" }}>
                    Enable AI Summaries first to configure performance settings.
                  </div>
                </PanelSectionRow>
              </PanelSection>
            ) : (
              <>
                <PanelSection title="Thermal Limits">
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
                </PanelSection>
                <PanelSection title="Adaptive Throttling">
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
                </PanelSection>
              </>
            ))}
      {selectedPage === 4 && (
              <PanelSection title="Display & Interaction">
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
            )}
      {selectedPage === 5 && (
              <PanelSection title="Advanced">
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
                <PanelSectionRow>
                  <ToggleField
                    label="Debug Mode"
                    description="Enable detailed logging for troubleshooting"
                    checked={settings.debugMode ?? false}
                    onChange={(value) => updateSetting("debugMode", value)}
                    disabled={loading}
                  />
                </PanelSectionRow>
              </PanelSection>
            )}
      {showHeatmap && (
        <ForensicHeatmap
          hours={6}
          onClose={() => setShowHeatmap(false)}
        />
      )}
    </div>
  );
}
