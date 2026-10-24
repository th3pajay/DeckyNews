import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.sqlite_writer import SqliteWriter


_NOMINAL_TDP_WATTS = 10.0


class TelemetryDB:

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._last_vacuum_time = 0
        self.logger = logging.getLogger("TelemetryDB")
        self._writer = SqliteWriter(
            db_path,
            pragmas=(
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA cache_size=-64000",
            ),
            maxsize=100,
            low_priority=True,
            name="TelemetryWriter",
        )

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        return self._writer.connection()

    def flush(self):
        self._writer.flush()

    def _init_schema(self):
        conn = self._get_connection()


        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER DEFAULT (strftime('%s', 'now')),
                engine_type TEXT,
                model_id TEXT,

                /* I. AI Performance (9 columns) */
                tps REAL,
                ttft REAL,
                prompt_eval_time REAL,
                total_tokens INTEGER,
                stop_reason TEXT,
                ram_delta_mb REAL,
                load_duration REAL,

                /* II. Hardware & Thermals (6 columns) */
                cpu_peak_temp REAL,
                temp_delta REAL,
                tdp_watts REAL,
                fan_rpm INTEGER,
                energy_mwh REAL,
                cooldown_vel REAL,

                /* III. Article Metadata (6 columns) */
                comp_ratio REAL,
                flesch_score REAL,
                ai_probability REAL,
                dup_count INTEGER,
                dedup_lat REAL,
                ttl_days INTEGER,

                /* IV. Network & Source (4 columns) */
                fetch_lat REAL,
                src_success REAL,
                cloud_bypass REAL,
                dl_kbps REAL,

                /* V. Plugin Orchestration (3 columns) */
                ipc_lat REAL,
                press_dur REAL,
                ui_fps_drop INTEGER
            )
        """)


        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON session_metrics(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON session_metrics(engine_type)")


        conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        try:
            conn.execute("ALTER TABLE session_metrics ADD COLUMN ai_probability REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE session_metrics ADD COLUMN model_id TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        conn.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1')")
        conn.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', strftime('%s', 'now'))")

        conn.commit()
        self.logger.info(f"Telemetry DB initialized at {self._db_path}")


    VALID_COLUMNS = frozenset({
        'timestamp', 'engine_type', 'model_id',

        'tps', 'ttft', 'prompt_eval_time', 'total_tokens', 'stop_reason',
        'ram_delta_mb', 'load_duration',

        'cpu_peak_temp', 'temp_delta', 'tdp_watts', 'fan_rpm',
        'energy_mwh', 'cooldown_vel',

        'comp_ratio', 'flesch_score', 'ai_probability', 'dup_count', 'dedup_lat', 'ttl_days',

        'fetch_lat', 'src_success', 'cloud_bypass', 'dl_kbps',

        'ipc_lat', 'press_dur', 'ui_fps_drop',
    })

    def _execute_insert(self, metrics: Dict[str, Any]):
        try:
            conn = self._get_connection()


            filtered = {k: v for k, v in metrics.items() if k in self.VALID_COLUMNS}


            dropped = set(metrics.keys()) - set(filtered.keys())
            if dropped:
                self.logger.warning(f"Dropped non-schema fields from telemetry insert: {dropped}")

            if not filtered:
                self.logger.warning("No valid columns in telemetry payload, skipping insert")
                return


            columns = list(filtered.keys())
            placeholders = ', '.join(['?' for _ in columns])
            column_str = ', '.join(columns)

            query = f"INSERT INTO session_metrics ({column_str}) VALUES ({placeholders})"
            values = [filtered[col] for col in columns]

            conn.execute(query, values)
            conn.commit()



            if time.time() - self._last_vacuum_time > 43200:
                conn.execute("PRAGMA optimize")
                self._last_vacuum_time = time.time()
                self.logger.debug("Telemetry DB optimized")

        except Exception as e:
            self.logger.error(f"Failed to insert telemetry record: {e}")

    def _execute_prune(self, hours: int):
        try:
            conn = self._get_connection()
            cutoff = int(time.time()) - (hours * 3600)


            result = conn.execute(
                "DELETE FROM session_metrics WHERE id IN "
                "(SELECT id FROM session_metrics WHERE timestamp < ? LIMIT 500)",
                (cutoff,)
            )
            conn.commit()

            deleted = result.rowcount
            if deleted > 0:
                self.logger.info(f"Pruned {deleted} old telemetry records (older than {hours}h)")

        except Exception as e:
            self.logger.error(f"Failed to prune telemetry records: {e}")

    def insert_session(self, metrics: Dict[str, Any]) -> int:
        if self._writer.submit_nowait(lambda: self._execute_insert(metrics)):
            return 0
        self.logger.warning("Telemetry write queue full, dropping record")
        return -1

    def prune_old_records(self, hours: int = 48):
        if not self._writer.submit_nowait(lambda: self._execute_prune(hours)):
            self.logger.warning("Telemetry write queue full, skipping prune")

    def get_heatmap_data(self, hours: int = 6) -> List[Dict[str, Any]]:
        try:
            conn = self._get_connection()
            cutoff = int(time.time()) - (hours * 3600)


            cursor = conn.execute(
                """
                SELECT * FROM session_metrics
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 500
                """,
                (cutoff,)
            )


            records = []
            for row in cursor:
                records.append(dict(row))

            return records

        except Exception as e:
            self.logger.error(f"Failed to fetch heatmap data: {e}")
            return []

    def get_summary_stats(self) -> Dict[str, Any]:
        try:
            conn = self._get_connection()

            stats = {}


            stats['total_sessions'] = conn.execute(
                "SELECT COUNT(*) FROM session_metrics"
            ).fetchone()[0]


            cursor = conn.execute("""
                SELECT
                    AVG(tps) as avg_tps,
                    MAX(cpu_peak_temp) as peak_temp,
                    SUM(energy_mwh) as total_energy,
                    SUM(total_tokens) as total_tokens
                FROM session_metrics
            """)
            row = cursor.fetchone()

            stats['avg_tps'] = row['avg_tps'] or 0
            stats['peak_temp'] = row['peak_temp'] or 0
            stats['total_energy'] = row['total_energy'] or 0
            stats['total_tokens'] = row['total_tokens'] or 0

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get summary stats: {e}")
            return {}

    def clear_all_records(self):
        try:
            conn = self._get_connection()
            conn.execute("DELETE FROM session_metrics")
            conn.commit()
            self.logger.info("All telemetry records cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear telemetry data: {e}")
            raise

    def shutdown(self):
        self._writer.close()
        self.logger.info("Telemetry DB shut down")


@dataclass
class TelemetryProbes:
    cpu_temperature: Callable[[], Optional[float]]
    dup_count: Callable[[str], int]
    dedup_latency: Callable[[], Optional[float]]
    is_game_running: Optional[Callable[[], bool]] = None


class TelemetryManager:

    def __init__(self, db_path: Path, probes: "TelemetryProbes"):
        self.db = TelemetryDB(db_path)
        self.probes = probes
        self.logger = logging.getLogger("TelemetryManager")


        self._session_buffer: Dict[str, Dict[str, Any]] = {}
        self._idle_timer: Optional[threading.Timer] = None


        self._baseline_cpu_temp = 0.0
        self._baseline_ram_mb = 0.0

    def start_session(self, article_id: str, model_id: str = "unknown") -> Optional[str]:

        if self.probes.is_game_running is not None and self.probes.is_game_running():
            self.logger.debug("Telemetry disabled during gaming")
            return None

        session_id = f"{article_id}_{int(time.time() * 1000)}"


        self._session_buffer[session_id] = {
            'timestamp': int(time.time()),
            'engine_type': 'llamafile',
            'model_id': model_id,
        }


        self._baseline_cpu_temp = self._get_cpu_temp()
        self._baseline_ram_mb = self._get_ram_usage_mb()

        return session_id

    def record_timing(self, session_id: Optional[str], phase: str, duration: float):
        if session_id is None or session_id not in self._session_buffer:
            return

        session = self._session_buffer[session_id]


        if phase == 'fetch':
            session['fetch_lat'] = duration
        elif phase == 'load':
            session['load_duration'] = duration
        elif phase == 'inference':
            session['inference_duration'] = duration
        elif phase == 'dedup':
            session['dedup_lat'] = duration
        elif phase == 'ipc':
            session['ipc_lat'] = duration

    def record_hardware(self, session_id: Optional[str]):
        if session_id is None or session_id not in self._session_buffer:
            return

        session = self._session_buffer[session_id]

        cpu_temp = self._get_cpu_temp()
        session['cpu_peak_temp'] = cpu_temp
        session['temp_delta'] = cpu_temp - self._baseline_cpu_temp

        current_ram = self._get_ram_usage_mb()
        session['ram_delta_mb'] = current_ram - self._baseline_ram_mb

        session['fan_rpm'] = self._get_fan_rpm()

    def finalize_session(self, session_id: Optional[str], summary_result: Dict[str, Any], article_url: Optional[str] = None):
        if session_id is None or session_id not in self._session_buffer:
            return

        try:
            session = self._session_buffer.pop(session_id)

            session.update({
                'tps': summary_result.get('tps'),
                'ttft': summary_result.get('ttft'),
                'prompt_eval_time': summary_result.get('prompt_eval_time'),
                'total_tokens': summary_result.get('total_tokens'),
                'stop_reason': summary_result.get('stop_reason'),
                'load_duration': summary_result.get('load_duration'),
            })


            self._calculate_derived_metrics(session, summary_result, article_url)


            self.db.insert_session(session)


            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None


            self.db.prune_old_records(hours=48)

            self.logger.debug(f"Telemetry session finalized: {session_id}")

        except Exception as e:
            self.logger.error(f"Telemetry finalize error (non-fatal): {e}")

    def _calculate_derived_metrics(self, session: Dict[str, Any], summary_result: Dict[str, Any], article_url: Optional[str] = None):
        total_duration = session.get('inference_duration', 0)
        session['energy_mwh'] = (_NOMINAL_TDP_WATTS * total_duration) / 3.6

        temp_delta = session.get('temp_delta', 0)
        if total_duration > 0:
            session['cooldown_vel'] = -abs(temp_delta) / total_duration
        else:
            session['cooldown_vel'] = 0.0

        summary_text = summary_result.get('summary', '')
        original_text = summary_result.get('original_text', '')
        if original_text and summary_text:
            session['comp_ratio'] = len(original_text) / max(1, len(summary_text))


        session['ui_fps_drop'] = 0
        session['press_dur'] = 0.0
        session['src_success'] = 100.0
        session['cloud_bypass'] = 0.0
        session['dl_kbps'] = 0.0
        if article_url:
            try:
                session['dup_count'] = self.probes.dup_count(article_url)
            except Exception:
                session['dup_count'] = 0
            session['dedup_lat'] = self.probes.dedup_latency()
        else:
            session['dup_count'] = 0
        session['ttl_days'] = 7


        session.pop('inference_duration', None)

    def _get_cpu_temp(self) -> float:
        try:
            temp = self.probes.cpu_temperature()
            return temp or 0.0
        except Exception as e:
            self.logger.warning(f"CPU temp read failed: {e}")
        return 0.0

    def _get_ram_usage_mb(self) -> float:
        try:
            import psutil
            return psutil.virtual_memory().used / (1024 * 1024)
        except Exception as e:
            self.logger.warning(f"RAM usage read failed: {e}")
        return 0.0

    def _get_fan_rpm(self) -> int:
        try:
            hwmon_base = Path("/sys/class/hwmon")
            if not hwmon_base.exists():
                return 0

            for hwmon_dir in hwmon_base.iterdir():
                fan_path = hwmon_dir / "fan1_input"
                if fan_path.exists():
                    rpm = int(fan_path.read_text().strip())
                    return rpm

        except Exception as e:
            self.logger.debug(f"Fan RPM read failed: {e}")

        return 0

    def export_dossier(self, output_path: Path):
        try:

            stats = self.db.get_summary_stats()


            records = self.db.get_heatmap_data(hours=48)[:100]

            with open(output_path, 'w') as f:

                f.write("=" * 80 + "\n")
                f.write("DECKYNEWS FORENSIC DOSSIER\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"Total Sessions: {stats.get('total_sessions', 0)}\n")
                f.write("=" * 80 + "\n\n")


                f.write("EXECUTIVE SUMMARY\n")
                f.write("-" * 17 + "\n")
                f.write(f"Average TPS:        {stats.get('avg_tps', 0):.1f} tokens/sec\n")
                f.write(f"Peak CPU Temp:      {stats.get('peak_temp', 0):.1f}°C\n")
                f.write(f"Total Energy:       {stats.get('total_energy', 0):.1f} mWh\n")
                f.write(f"Total Tokens:       {stats.get('total_tokens', 0):,}\n")


                f.write("\n\nSESSION RECORDS\n")
                f.write("-" * 15 + "\n\n")

                for idx, record in enumerate(records, 1):
                    timestamp = datetime.fromtimestamp(record['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"[Session #{idx}] {timestamp}\n")


                    f.write("  I. AI PERFORMANCE\n")
                    f.write(f"    • TPS:              {record.get('tps', 0) or 0:.1f} tokens/sec\n")
                    f.write(f"    • TTFT:             {record.get('ttft', 0) or 0:.0f} ms\n")
                    f.write(f"    • Prompt Eval:      {record.get('prompt_eval_time', 0) or 0:.0f} ms\n")
                    f.write(f"    • Total Tokens:     {record.get('total_tokens', 0) or 0}\n")
                    f.write(f"    • Stop Reason:      {record.get('stop_reason') or 'N/A'}\n")
                    f.write(f"    • RAM Delta:        {record.get('ram_delta_mb', 0) or 0:+.0f} MB\n")
                    f.write(f"    • Load Duration:    {record.get('load_duration', 0) or 0:.1f} s\n\n")


                    f.write("  II. HARDWARE & THERMALS\n")
                    f.write(f"    • CPU Peak:         {record.get('cpu_peak_temp', 0) or 0:.1f}°C\n")
                    f.write(f"    • Temp Delta:       {record.get('temp_delta', 0) or 0:+.1f}°C\n")
                    f.write(f"    • Fan RPM:          {record.get('fan_rpm', 0) or 0:,} RPM\n")
                    f.write(f"    • Energy Cost:      {record.get('energy_mwh', 0) or 0:.2f} mWh\n")
                    f.write(f"    • Cooldown Vel:     {record.get('cooldown_vel', 0) or 0:.2f}°C/s\n\n")


                    f.write("  III. ARTICLE METADATA\n")
                    f.write(f"    • Compression:      {record.get('comp_ratio', 0) or 0:.1f}:1\n")
                    f.write(f"    • Duplicates:       {record.get('dup_count', 0) or 0}\n")
                    f.write(f"    • Dedup Latency:    {record.get('dedup_lat', 0) or 0:.3f} s\n")
                    f.write(f"    • TTL:              {record.get('ttl_days', 0) or 0} days\n\n")


                    f.write("  IV. NETWORK & SOURCE\n")
                    f.write(f"    • Fetch Latency:    {record.get('fetch_lat', 0) or 0:.2f} s\n")
                    f.write(f"    • Source Success:   {record.get('src_success', 0) or 0:.0f}%\n")
                    f.write(f"    • Cloud Bypass:     {record.get('cloud_bypass', 0) or 0:.0f}%\n")
                    f.write(f"    • Download Speed:   {record.get('dl_kbps', 0) or 0:.0f} kbps\n\n")


                    f.write("  V. PLUGIN ORCHESTRATION\n")
                    f.write(f"    • IPC Latency:      {record.get('ipc_lat', 0) or 0:.3f} s\n")
                    f.write(f"    • Press Duration:   {record.get('press_dur', 0) or 0:.2f} s\n")
                    f.write(f"    • UI FPS Drop:      {record.get('ui_fps_drop', 0) or 0} frames\n\n")


                f.write("\n" + "=" * 80 + "\n")
                f.write("END OF DOSSIER\n")
                f.write("=" * 80 + "\n")

            self.logger.info(f"Telemetry dossier exported to {output_path}")

        except Exception as e:
            self.logger.error(f"Failed to export dossier: {e}")
            raise

    def shutdown(self):
        if self._idle_timer:
            self._idle_timer.cancel()
        self.db.shutdown()
