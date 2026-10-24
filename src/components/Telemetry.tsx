import { useState, useEffect } from "react";
import { Focusable, GamepadButton, GamepadEvent } from "@decky/ui";
import { toaster } from "@decky/api";
import { FaSpinner } from "react-icons/fa";
import { getTelemetryHeatmap, exportTelemetryDossier, clearTelemetryData } from "../api";
import { HeatmapCell as HeatmapCellData, TelemetryHeatmapResponse, ExportDossierResponse } from "../types";

void ({} as TelemetryHeatmapResponse);
void ({} as ExportDossierResponse);

interface HeatmapCellProps {
  data: HeatmapCellData;
  isFocused: boolean;
  colorBy: 'tps' | 'temp';
  onClick: () => void;
}

interface MetricRow { label: string; key: string; value: any; unit: string; }

interface MetricInspectorProps {
  cell: HeatmapCellData;
  onClose: () => void;
}

interface ForensicHeatmapProps {
  hours?: number;
  onClose: () => void;
}

const HeatmapCellComponent: React.FC<HeatmapCellProps> = ({ data, isFocused, colorBy, onClick }) => {
  const tps = data.tps ?? 0;
  const rawIntensity = colorBy === 'temp'
    ? Math.min(1, (data.cpu_peak_temp ?? 0) / 100)
    : Math.min(1, tps / 50);

  const getColor = (val: number): string => {
    const bandAlpha = (bandVal: number) => 0.4 + (bandVal / 0.25) * 0.6;
    if (val < 0.25) return `rgba(26, 159, 255, ${bandAlpha(val)})`;
    if (val < 0.5)  return `rgba(76, 175, 80, ${bandAlpha(val - 0.25)})`;
    if (val < 0.75) return `rgba(255, 193, 7, ${bandAlpha(val - 0.5)})`;
    return `rgba(244, 67, 54, ${bandAlpha(val - 0.75)})`;
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

export { HeatmapCellComponent as HeatmapCell };

const METRIC_THRESHOLDS: Record<string, { good: [number, number]; warn: [number, number] }> = {
  tps:           { good: [5, 50],    warn: [1, 5] },
  ttft:          { good: [0, 2000],  warn: [2000, 5000] },
  cpu_peak_temp: { good: [0, 75],    warn: [75, 85] },
  temp_delta:    { good: [0, 10],    warn: [10, 20] },
  src_success:   { good: [80, 100],  warn: [50, 80] },
  comp_ratio:    { good: [2, 10],    warn: [1, 2] },
  ram_delta_mb:  { good: [0, 200],   warn: [200, 500] },
};

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

const METRIC_SECTIONS: { title: string; metrics: { label: string; key: keyof HeatmapCellData; unit: string }[] }[] = [
  {
    title: "AI Performance",
    metrics: [
      { label: "Tokens/sec", key: "tps", unit: "T/s" },
      { label: "Time to First Token", key: "ttft", unit: "ms" },
      { label: "Prompt Eval Time", key: "prompt_eval_time", unit: "ms" },
      { label: "Total Tokens", key: "total_tokens", unit: "" },
      { label: "Stop Reason", key: "stop_reason", unit: "" },
      { label: "RAM Delta", key: "ram_delta_mb", unit: "MB" },
      { label: "Load Duration", key: "load_duration", unit: "s" },
    ]
  },
  {
    title: "Hardware & Thermals",
    metrics: [
      { label: "CPU Peak Temp", key: "cpu_peak_temp", unit: "°C" },
      { label: "Temp Delta", key: "temp_delta", unit: "°C" },
      { label: "Fan RPM", key: "fan_rpm", unit: "RPM" },
      { label: "Energy Cost", key: "energy_mwh", unit: "mWh" },
      { label: "Cooldown Velocity", key: "cooldown_vel", unit: "°C/s" },
    ]
  },
  {
    title: "Article Metadata",
    metrics: [
      { label: "Compression Ratio", key: "comp_ratio", unit: ":1" },
      { label: "Duplicates", key: "dup_count", unit: "" },
      { label: "Dedup Latency", key: "dedup_lat", unit: "s" },
      { label: "TTL", key: "ttl_days", unit: "days" },
    ]
  },
  {
    title: "Network & Source",
    metrics: [
      { label: "Fetch Latency", key: "fetch_lat", unit: "s" },
      { label: "Source Success", key: "src_success", unit: "%" },
      { label: "Cloud Bypass", key: "cloud_bypass", unit: "%" },
      { label: "Download Speed", key: "dl_kbps", unit: "kbps" },
    ]
  },
  {
    title: "Plugin Orchestration",
    metrics: [
      { label: "IPC Latency", key: "ipc_lat", unit: "s" },
      { label: "Press Duration", key: "press_dur", unit: "s" },
      { label: "UI FPS Drop", key: "ui_fps_drop", unit: "frames" },
    ]
  }
];

const MetricInspector: React.FC<MetricInspectorProps> = ({ cell, onClose }) => {
  const sections: { title: string; metrics: MetricRow[] }[] = METRIC_SECTIONS.map(s => ({
    title: s.title,
    metrics: s.metrics.map(m => ({ ...m, value: cell[m.key] })),
  }));

  const MODEL_NAMES: Record<string, string> = {
    "qwen2.5-0.5b": "Qwen2.5-0.5B",
    "mobilellm-600m": "MobileLLM-600M",
    "llama3.2-1b": "Llama 3.2-1B",
    "qwen3-0.6b-thinking": "Qwen3-0.6B Thinking",
    "qwen3-0.6b": "Qwen3-0.6B",
    "smollm2-360m": "SmolLM2-360M",
    "gemma3-270m": "Gemma 3 270M",
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

export { MetricInspector };

const LINE_SERIES = [
  { key: "tps",            label: "TPS",     color: "#1a9fff" },
  { key: "cpu_peak_temp",  label: "CPU °C",  color: "#ff6b6b" },
  { key: "ram_delta_mb",   label: "RAM MB",  color: "#cc5de8" },
] as const;

const CHART_W = 290;
const CHART_H = 150;
const CHART_PAD = 6;

const clockLabel = (ts: number) => {
  const t = new Date(ts * 1000);
  return `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
};

const TimeSeriesChart: React.FC<{ data: HeatmapCellData[] }> = ({ data }) => {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [idx, setIdx] = useState(Math.max(0, data.length - 1));
  const [tab, setTab] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);

  if (data.length === 0) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '200px', color: '#8b8f98', fontSize: '13px' }}>
        No data to chart
      </div>
    );
  }

  const last = data.length - 1;
  const sel = data[Math.min(idx, last)];
  const xAt = (i: number) => CHART_PAD + (last === 0 ? 0.5 : i / last) * (CHART_W - 2 * CHART_PAD);
  const toggle = (key: string) =>
    setHidden(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const scrub = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const f = ((e.clientX - r.left) / r.width * CHART_W - CHART_PAD) / (CHART_W - 2 * CHART_PAD);
    setIdx(Math.round(Math.min(1, Math.max(0, f)) * last));
  };

  const visible = LINE_SERIES.filter(s => !hidden.has(s.key));
  const yFor = visible.map(s => {
    const vals = data.map(c => c[s.key]).filter((v): v is number => v !== null);
    const mn = Math.min(...vals);
    const range = Math.max(...vals) - mn || 1;
    return (c: HeatmapCellData) => {
      const v = c[s.key];
      return v === null ? null : 8 + (1 - (v - mn) / range) * (CHART_H - 16);
    };
  });

  const paths = visible.map((s, i) => {
    const pts = data.flatMap((c, j) => {
      const y = yFor[i](c);
      return y === null ? [] : [`${xAt(j).toFixed(1)},${y.toFixed(1)}`];
    });
    return <polyline key={s.key} points={pts.join(" ")} fill="none" stroke={s.color} strokeWidth={1.8} strokeLinejoin="round" />;
  });

  const section = METRIC_SECTIONS[tab];

  return (
    <Focusable
      style={{ padding: '12px 8px' }}
      onGamepadDirection={(e: GamepadEvent) => {
        if (e.detail.button === GamepadButton.DIR_LEFT) setIdx(i => Math.max(0, i - 1));
        else if (e.detail.button === GamepadButton.DIR_RIGHT) setIdx(i => Math.min(last, i + 1));
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px' }}>
        {LINE_SERIES.map(s => (
          <Focusable
            key={s.key}
            style={{
              padding: '3px 9px',
              borderRadius: '4px',
              fontSize: '11px',
              cursor: 'pointer',
              background: hidden.has(s.key) ? 'rgba(61,68,80,0.3)' : `${s.color}22`,
              border: `1px solid ${hidden.has(s.key) ? '#3d4450' : s.color}`,
              color: hidden.has(s.key) ? '#8b8f98' : s.color,
              transition: 'all 0.15s',
            }}
            onActivate={() => toggle(s.key)}
          >
            {s.label}
          </Focusable>
        ))}
      </div>

      <div style={{ background: 'rgba(61,68,80,0.22)', border: '1px solid rgba(61,68,80,0.55)', borderRadius: '8px', padding: '8px 6px 4px', touchAction: 'none' }}>
        <svg
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          style={{ width: '100%', display: 'block' }}
          onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setScrubbing(true); scrub(e); }}
          onPointerMove={(e) => scrubbing && scrub(e)}
          onPointerUp={() => setScrubbing(false)}
          onPointerCancel={() => setScrubbing(false)}
        >
          {[0, 0.5, 1].map(f => (
            <line key={f} x1={0} x2={CHART_W} y1={8 + f * (CHART_H - 16)} y2={8 + f * (CHART_H - 16)} stroke="rgba(61,68,80,0.35)" />
          ))}
          {paths}
          <line x1={xAt(idx)} x2={xAt(idx)} y1={0} y2={CHART_H} stroke="#fff" strokeOpacity={0.5} strokeDasharray="3 3" />
          {visible.map((s, i) => {
            const y = yFor[i](sel);
            return y === null ? null : <circle key={s.key} cx={xAt(idx)} cy={y} r={3.5} fill={s.color} stroke="#0e141b" strokeWidth={1.5} />;
          })}
        </svg>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: '#8b8f98', padding: '0 2px' }}>
          <span>{clockLabel(data[0].timestamp)}</span>
          <span>{clockLabel(data[Math.floor(last / 2)].timestamp)}</span>
          <span>{clockLabel(data[last].timestamp)}</span>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '8px 0 6px' }}>
        <span style={{ fontWeight: 600, fontSize: '13px', color: '#e8eaed' }}>Session {clockLabel(sel.timestamp)}</span>
        <span style={{ fontSize: '11px', color: '#8b8f98' }}>{sel.model_id ?? sel.engine_type}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px', marginBottom: '8px' }}>
        {([["tps", "T/s", "", 1], ["cpu_peak_temp", "peak", "°", 0], ["ram_delta_mb", "RAM MB", "", 0]] as const).map(([key, label, unit, digits]) => {
          const v = sel[key];
          return (
            <div key={key} style={{ background: 'rgba(61,68,80,0.22)', border: '1px solid rgba(61,68,80,0.55)', borderRadius: '6px', padding: '6px', textAlign: 'center' }}>
              <div style={{ fontSize: '15px', fontWeight: 600, color: v === null ? '#8b8f98' : getMetricColor(key, v) }}>
                {v === null ? '—' : `${v.toFixed(digits)}${unit}`}
              </div>
              <div style={{ fontSize: '9px', color: '#8b8f98' }}>{label}</div>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', border: '1px solid rgba(61,68,80,0.55)', borderRadius: '6px', overflow: 'hidden', marginBottom: '4px' }}>
        {METRIC_SECTIONS.map((s, i) => (
          <Focusable
            key={s.title}
            style={{
              flex: 1,
              textAlign: 'center',
              padding: '6px 0',
              fontSize: '10px',
              cursor: 'pointer',
              background: i === tab ? 'rgba(26,159,255,0.25)' : 'rgba(61,68,80,0.22)',
              color: i === tab ? '#1a9fff' : '#b8bcbf',
            }}
            onActivate={() => setTab(i)}
          >
            {s.title.split(/[ &]/)[0]}
          </Focusable>
        ))}
      </div>

      {section.metrics.map(m => {
        const v = sel[m.key];
        return (
          <div key={m.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 2px', borderBottom: '1px solid rgba(61,68,80,0.3)', fontSize: '12px' }}>
            <span style={{ flex: 1, color: '#8b8f98' }}>{m.label}</span>
            <span style={{ fontWeight: 600, color: typeof v === 'number' ? getMetricColor(m.key, v) : '#e8eaed' }}>
              {formatValue(v, m.unit)}
            </span>
          </div>
        );
      })}
    </Focusable>
  );
};

export const TelemetrySummaryStrip: React.FC = () => {
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

export const ForensicHeatmap: React.FC<ForensicHeatmapProps> = ({ hours = 6, onClose }) => {
  const [data, setData] = useState<HeatmapCellData[]>([]);
  const [selectedCell, setSelectedCell] = useState<HeatmapCellData | null>(null);
  const [colorBy, setColorBy] = useState<'tps' | 'temp'>('tps');
  const [view, setView] = useState<'heatmap' | 'graph'>('heatmap');
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
        loadData();
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
      {}
      <div style={{ padding: '16px', borderBottom: '1px solid #3d4450', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '20px', color: '#e8eaed', marginBottom: '4px' }}>
            Forensic Heatmap
          </h2>
          <div style={{ fontSize: '12px', color: '#8b8f98' }}>
            Last {hours} hours • {Math.min(data.length, 60)} sessions{data.length > 60 ? ` (of ${data.length})` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          {(['heatmap', 'graph'] as const).map(v => (
            <Focusable
              key={v}
              style={{
                padding: '4px 10px',
                background: view === v ? 'rgba(26, 159, 255, 0.25)' : 'rgba(61, 68, 80, 0.3)',
                border: `1px solid ${view === v ? 'rgba(26, 159, 255, 0.6)' : 'rgba(61, 68, 80, 0.6)'}`,
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '11px',
                color: view === v ? '#1a9fff' : '#b8bcbf',
                transition: 'all 0.15s',
              }}
              onActivate={() => setView(v)}
            >
              {v === 'heatmap' ? 'Heatmap' : 'Graph'}
            </Focusable>
          ))}
          {view === 'heatmap' && (['tps', 'temp'] as const).map(mode => (
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

      {}
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
        ) : view === 'graph' ? (
          <TimeSeriesChart data={data} />
        ) : (
          <>
          <div style={gridStyle}>
            {data.slice(0, 60).map((cell) => (
              <HeatmapCellComponent
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

      {}
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

      {}
      {selectedCell && (
        <MetricInspector cell={selectedCell} onClose={() => setSelectedCell(null)} />
      )}
    </div>
  );
};
