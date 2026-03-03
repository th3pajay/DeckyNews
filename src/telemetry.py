"""
Telemetry and Forensic Heatmap System for DeckyNews.
Captures LLM performance metrics in the 25-column Dossier-25 SQLite schema.
48-hour ring buffer; WAL mode; background write queue.
"""

import sqlite3
import threading
import queue
import time
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import re


class TelemetryDB:
    """Thread-safe SQLite database for telemetry data. Mirrors database.py threading pattern."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._local = threading.local()
        self._write_queue = queue.Queue(maxsize=100)
        self._shutdown_flag = threading.Event()
        self._last_commit_time = 0
        self._last_vacuum_time = 0
        self.logger = logging.getLogger("TelemetryDB")

        self._init_schema()
        self._start_write_worker()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection with WAL mode."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self._local.conn.row_factory = sqlite3.Row

            # Enable WAL mode for crash safety
            try:
                self._local.conn.execute("PRAGMA journal_mode=WAL")
                self._local.conn.execute("PRAGMA synchronous=NORMAL")
                self._local.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
                self.logger.debug("WAL mode enabled for telemetry database")
            except sqlite3.OperationalError as e:
                self.logger.warning(f"WAL mode failed, using default: {e}")
                # Fallback to DELETE mode (default)
                pass

        return self._local.conn

    def _init_schema(self):
        """Initialize database schema with exact 25-column Dossier-25 structure."""
        conn = self._get_connection()

        # Main metrics table (25 columns + id + timestamp)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER DEFAULT (strftime('%s', 'now')),
                engine_type TEXT,

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

        # Indexes for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON session_metrics(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON session_metrics(engine_type)")

        # Metadata table
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

        conn.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1')")
        conn.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', strftime('%s', 'now'))")

        conn.commit()
        self.logger.info(f"Telemetry DB initialized at {self._db_path}")

    def _start_write_worker(self):
        """Start background thread for async writes."""
        worker = threading.Thread(target=self._write_worker, daemon=True, name="TelemetryWriter")
        worker.start()
        self.logger.debug("Background write worker started for telemetry")

    def _write_worker(self):
        """
        Background worker thread that consumes write queue.
        Runs at lowest priority to avoid interfering with AI inference.
        """
        # Set lowest CPU priority (nice 19)
        try:
            os.nice(19)
        except Exception:
            pass  # Windows doesn't support nice

        while not self._shutdown_flag.is_set():
            try:
                # Block for up to 1 second waiting for work
                item = self._write_queue.get(timeout=1.0)

                if item is None:  # Shutdown signal
                    break

                action, data = item

                if action == "insert":
                    self._execute_insert(data)
                elif action == "prune":
                    self._execute_prune(data)

                self._write_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Telemetry write worker error: {e}", exc_info=True)

    # Whitelist of valid database columns in session_metrics.
    # Any key NOT in this set is silently dropped before INSERT to prevent
    # "table session_metrics has no column named X" errors from intermediate
    # fields (e.g. inference_duration) leaking into the insert payload.
    VALID_COLUMNS = frozenset({
        'timestamp', 'engine_type',
        # I. AI Performance
        'tps', 'ttft', 'prompt_eval_time', 'total_tokens', 'stop_reason',
        'ram_delta_mb', 'load_duration',
        # II. Hardware & Thermals
        'cpu_peak_temp', 'temp_delta', 'tdp_watts', 'fan_rpm',
        'energy_mwh', 'cooldown_vel',
        # III. Article Metadata
        'comp_ratio', 'flesch_score', 'ai_probability', 'dup_count', 'dedup_lat', 'ttl_days',
        # IV. Network & Source
        'fetch_lat', 'src_success', 'cloud_bypass', 'dl_kbps',
        # V. Plugin Orchestration
        'ipc_lat', 'press_dur', 'ui_fps_drop',
    })

    def _execute_insert(self, metrics: Dict[str, Any]):
        """Execute INSERT on worker thread."""
        try:
            conn = self._get_connection()

            # Filter to only valid schema columns (defensive against buffer pollution)
            filtered = {k: v for k, v in metrics.items() if k in self.VALID_COLUMNS}

            # Log any dropped keys for debugging (non-fatal)
            dropped = set(metrics.keys()) - set(filtered.keys())
            if dropped:
                self.logger.warning(f"Dropped non-schema fields from telemetry insert: {dropped}")

            if not filtered:
                self.logger.warning("No valid columns in telemetry payload, skipping insert")
                return

            # Build column list and placeholders
            columns = list(filtered.keys())
            placeholders = ', '.join(['?' for _ in columns])
            column_str = ', '.join(columns)

            query = f"INSERT INTO session_metrics ({column_str}) VALUES ({placeholders})"
            values = [filtered[col] for col in columns]

            conn.execute(query, values)
            conn.commit()

            self._last_commit_time = time.time()

            # Adaptive vacuum scheduling (every 12 hours)
            if time.time() - self._last_vacuum_time > 43200:
                conn.execute("PRAGMA optimize")
                self._last_vacuum_time = time.time()
                self.logger.debug("Telemetry DB optimized")

        except Exception as e:
            self.logger.error(f"Failed to insert telemetry record: {e}")

    def _execute_prune(self, hours: int):
        """Execute DELETE for records older than N hours."""
        try:
            conn = self._get_connection()
            cutoff = int(time.time()) - (hours * 3600)

            # Prune in batches of 500 rows
            result = conn.execute(
                "DELETE FROM session_metrics WHERE timestamp < ? LIMIT 500",
                (cutoff,)
            )
            conn.commit()

            deleted = result.rowcount
            if deleted > 0:
                self.logger.info(f"Pruned {deleted} old telemetry records (older than {hours}h)")

        except Exception as e:
            self.logger.error(f"Failed to prune telemetry records: {e}")

    def insert_session(self, metrics: Dict[str, Any]) -> int:
        """
        Non-blocking insert via write queue.

        Args:
            metrics: Dictionary with telemetry data (must match schema columns)

        Returns:
            0 on success (queued), -1 if queue full
        """
        try:
            self._write_queue.put(("insert", metrics), block=False)
            return 0
        except queue.Full:
            self.logger.warning("Telemetry write queue full, dropping record")
            return -1

    def prune_old_records(self, hours: int = 48):
        """
        Queue pruning task for records older than N hours.

        Args:
            hours: Retention window (default 48h ring buffer)
        """
        try:
            self._write_queue.put(("prune", hours), block=False)
        except queue.Full:
            self.logger.warning("Telemetry write queue full, skipping prune")

    def get_heatmap_data(self, hours: int = 6) -> List[Dict[str, Any]]:
        """
        Fetch telemetry data for heatmap visualization.

        Args:
            hours: Number of hours to fetch (default 6 for 12x5 grid)

        Returns:
            List of dictionaries with all 25 metrics
        """
        try:
            conn = self._get_connection()
            cutoff = int(time.time()) - (hours * 3600)

            # Fetch all columns for last N hours
            cursor = conn.execute(
                """
                SELECT * FROM session_metrics
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 500
                """,
                (cutoff,)
            )

            # Convert rows to dictionaries
            records = []
            for row in cursor:
                records.append(dict(row))

            return records

        except Exception as e:
            self.logger.error(f"Failed to fetch heatmap data: {e}")
            return []

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get executive summary statistics for export dossier."""
        try:
            conn = self._get_connection()

            stats = {}

            # Count total sessions
            stats['total_sessions'] = conn.execute(
                "SELECT COUNT(*) FROM session_metrics"
            ).fetchone()[0]

            # Average metrics
            cursor = conn.execute("""
                SELECT
                    AVG(tps) as avg_tps,
                    MAX(cpu_peak_temp) as peak_temp,
                    SUM(energy_mwh) as total_energy,
                    AVG(flesch_score) as avg_flesch,
                    SUM(total_tokens) as total_tokens
                FROM session_metrics
            """)
            row = cursor.fetchone()

            stats['avg_tps'] = row['avg_tps'] or 0
            stats['peak_temp'] = row['peak_temp'] or 0
            stats['total_energy'] = row['total_energy'] or 0
            stats['avg_flesch'] = row['avg_flesch'] or 0
            stats['total_tokens'] = row['total_tokens'] or 0

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get summary stats: {e}")
            return {}

    def clear_all_records(self):
        """Wipe all telemetry data (admin function)."""
        try:
            conn = self._get_connection()
            conn.execute("DELETE FROM session_metrics")
            conn.commit()
            self.logger.info("All telemetry records cleared")
        except Exception as e:
            self.logger.error(f"Failed to clear telemetry data: {e}")
            raise

    def shutdown(self):
        """Graceful shutdown of write worker."""
        self._shutdown_flag.set()
        self._write_queue.put(None)  # Wake up worker
        self.logger.info("Telemetry DB shutdown initiated")


class TelemetryManager:
    """
    High-level telemetry manager for metric capture and export.

    Responsibilities:
    - Capture metrics at 5 interception points
    - Calculate derived fields (flesch_score, energy_mwh, cooldown_vel)
    - Monitor hardware (CPU temp, RAM, fan RPM, TDP)
    - Batch commit strategy (after inference OR every 60s idle)
    """

    def __init__(self, db_path: Path, plugin_instance):
        self.db = TelemetryDB(db_path)
        self.plugin = plugin_instance
        self.logger = logging.getLogger("TelemetryManager")

        # Session buffer for accumulating metrics during pipeline
        self._session_buffer: Dict[str, Dict[str, Any]] = {}
        self._last_commit_time = 0
        self._idle_timer: Optional[threading.Timer] = None

        # Hardware baseline for delta calculations
        self._baseline_cpu_temp = 0.0
        self._baseline_ram_mb = 0.0

    def start_session(self, article_id: str) -> Optional[str]:
        """
        Initialize telemetry session for an article.

        Args:
            article_id: Unique article identifier

        Returns:
            session_id for tracking, or None if telemetry disabled
        """
        # Disable telemetry during gaming
        if hasattr(self.plugin, 'is_game_running') and self.plugin.is_game_running():
            self.logger.debug("Telemetry disabled during gaming")
            return None

        session_id = f"{article_id}_{int(time.time() * 1000)}"

        # Initialize session buffer (article_id only used for session_id, not stored in DB)
        self._session_buffer[session_id] = {
            'timestamp': int(time.time()),
            'engine_type': 'llamafile',  # Hardcoded for now
        }

        # Capture hardware baseline
        self._baseline_cpu_temp = self._get_cpu_temp()
        self._baseline_ram_mb = self._get_ram_usage_mb()

        return session_id

    def record_timing(self, session_id: Optional[str], phase: str, duration: float):
        """
        Capture timing at interception points.

        Args:
            session_id: Session identifier (can be None if disabled)
            phase: 'fetch', 'load', 'inference', 'dedup', 'ipc'
            duration: Duration in seconds
        """
        if session_id is None or session_id not in self._session_buffer:
            return

        session = self._session_buffer[session_id]

        # Map phase to schema column
        if phase == 'fetch':
            session['fetch_lat'] = duration
        elif phase == 'load':
            session['load_duration'] = duration
        elif phase == 'inference':
            session['inference_duration'] = duration  # Stored for energy calc
        elif phase == 'dedup':
            session['dedup_lat'] = duration
        elif phase == 'ipc':
            session['ipc_lat'] = duration

    def record_hardware(self, session_id: Optional[str]):
        """
        Capture hardware metrics (CPU temp, RAM, fan, TDP).

        Args:
            session_id: Session identifier
        """
        if session_id is None or session_id not in self._session_buffer:
            return

        session = self._session_buffer[session_id]

        # CPU temperature
        cpu_temp = self._get_cpu_temp()
        session['cpu_peak_temp'] = cpu_temp
        session['temp_delta'] = cpu_temp - self._baseline_cpu_temp

        # RAM usage
        current_ram = self._get_ram_usage_mb()
        session['ram_delta_mb'] = current_ram - self._baseline_ram_mb

        # Fan RPM
        session['fan_rpm'] = self._get_fan_rpm()

        # TDP estimation
        session['tdp_watts'] = self._estimate_tdp(cpu_temp)

    def finalize_session(self, session_id: Optional[str], summary_result: Dict[str, Any], article_url: Optional[str] = None):
        """
        Calculate derived metrics and commit to database.

        Args:
            session_id: Session identifier
            summary_result: Result from LLM inference (tps, ttft, tokens, etc.)
            article_url: URL of the article being summarized (for dup_count calculation)
        """
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

            # Calculate derived metrics
            self._calculate_derived_metrics(session, summary_result, article_url)

            # Commit to database (non-blocking)
            self.db.insert_session(session)
            self._last_commit_time = time.time()

            # Clear idle timer (we just committed)
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None

            # Schedule auto-prune (48-hour ring buffer)
            self.db.prune_old_records(hours=48)

            self.logger.debug(f"Telemetry session finalized: {session_id}")

        except Exception as e:
            self.logger.error(f"Telemetry finalize error (non-fatal): {e}")

    def _calculate_derived_metrics(self, session: Dict[str, Any], summary_result: Dict[str, Any], article_url: Optional[str] = None):
        """
        Calculate advanced metrics from captured data.

        Metrics:
        - energy_mwh: (tdp_watts × total_duration_seconds) / 3600
        - cooldown_vel: temp_delta / total_duration_seconds
        - flesch_score: 206.835 - 1.015×ASL - 84.6×ASW
        - comp_ratio: original_length / summary_length
        """
        # Energy cost calculation
        total_duration = session.get('inference_duration', 0)
        tdp = session.get('tdp_watts', 10.0)
        session['energy_mwh'] = (tdp * total_duration) / 3.6  # Convert to mWh

        # Thermal velocity (cooldown rate)
        temp_delta = session.get('temp_delta', 0)
        if total_duration > 0:
            session['cooldown_vel'] = -abs(temp_delta) / total_duration
        else:
            session['cooldown_vel'] = 0.0

        summary_text = summary_result.get('summary', '')
        if summary_text:
            session['flesch_score'] = self._calculate_flesch_score(summary_text)

        original_text = summary_result.get('original_text', '')
        if original_text and summary_text:
            session['comp_ratio'] = len(original_text) / max(1, len(summary_text))

        score = self._compute_ai_probability(original_text)
        if score >= 0:
            session['ai_probability'] = score

        # Placeholder for future metrics
        session['ui_fps_drop'] = 0  # TODO: Frame timing API integration
        session['press_dur'] = 0.0  # TODO: Track long-press duration
        session['src_success'] = 100.0  # TODO: Track RSS fetch success rate
        session['cloud_bypass'] = 0.0  # Llamafile is always local
        session['dl_kbps'] = 0.0  # TODO: Track download speed
        if article_url and hasattr(self.plugin, 'db_manager'):
            dedup_start = time.time()
            try:
                similarity_hash = self.plugin.db_manager.get_similarity_hash_by_url(article_url)
                if similarity_hash:
                    dup_count = self.plugin.db_manager.count_articles_by_similarity_hash(similarity_hash)
                    session['dup_count'] = max(0, dup_count - 1)
                else:
                    session['dup_count'] = 0
            except Exception:
                session['dup_count'] = 0
            session['dedup_lat'] = time.time() - dedup_start
        else:
            session['dup_count'] = 0
        session['ttl_days'] = 7  # Default TTL

        # Clean up intermediate fields that are NOT database columns.
        # These are temporary values used only for derived metric calculations above.
        session.pop('inference_duration', None)

    def _calculate_flesch_score(self, text: str) -> float:
        """
        Flesch Reading Ease: 206.835 - 1.015×ASL - 84.6×ASW

        ASL = Average Sentence Length (words/sentence)
        ASW = Average Syllables per Word

        Args:
            text: Article summary text

        Returns:
            Flesch score (0-100, higher = easier to read)
        """
        # Split into sentences
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        # Split into words
        words = text.split()

        if not sentences or not words:
            return 0.0

        # Count syllables
        syllables = sum(self._count_syllables(word) for word in words)

        # Calculate averages
        asl = len(words) / len(sentences)
        asw = syllables / len(words)

        # Flesch formula
        score = 206.835 - 1.015 * asl - 84.6 * asw

        return max(0, min(100, score))  # Clamp to 0-100

    def _count_syllables(self, word: str) -> int:
        """
        Simple syllable counter using vowel groups.

        Args:
            word: Single word

        Returns:
            Syllable count (minimum 1)
        """
        word = word.lower()
        vowels = 'aeiouy'
        count = 0
        prev_was_vowel = False

        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_was_vowel:
                count += 1
            prev_was_vowel = is_vowel

        # Adjust for silent 'e'
        if word.endswith('e') and count > 1:
            count -= 1

        return max(1, count)

    def _compute_ai_probability(self, text: str) -> float:
        if not text or len(text) < 150:
            return -1.0
        sample = text[:1500]
        words = re.findall(r'\b[a-zA-Z]{2,}\b', sample.lower())
        if len(words) < 40:
            return -1.0
        ttr = len(set(words)) / len(words)
        ttr_score = 1.0 - max(0.0, min(1.0, (ttr - 0.45) / 0.25))
        sentences = [s.strip() for s in re.split(r'[.!?]+', sample) if len(s.strip()) > 15]
        if len(sentences) >= 3:
            lengths = [len(s.split()) for s in sentences]
            mean_len = sum(lengths) / len(lengths)
            variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
            variance_score = 1.0 - min(1.0, variance / 50.0)
        else:
            variance_score = 0.5
        return round(0.65 * ttr_score + 0.35 * variance_score, 3)

    def _get_cpu_temp(self) -> float:
        try:
            rm = self.plugin.summarization_manager.resource_monitor
            temp = rm._get_cpu_temperature()
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
        """
        Read actual fan speed from hwmon sysfs.

        Steam Deck fan path: /sys/class/hwmon/hwmon*/fan1_input

        Returns:
            Fan RPM, or 0 if unavailable
        """
        try:
            hwmon_base = Path("/sys/class/hwmon")
            if not hwmon_base.exists():
                return 0  # Not on Linux

            for hwmon_dir in hwmon_base.iterdir():
                fan_path = hwmon_dir / "fan1_input"
                if fan_path.exists():
                    rpm = int(fan_path.read_text().strip())
                    return rpm

        except Exception as e:
            self.logger.debug(f"Fan RPM read failed: {e}")

        return 0  # Fallback

    def _estimate_tdp(self, cpu_temp: float) -> float:
        """
        Estimate Steam Deck TDP (typically 10-15W).

        Simple heuristic: base 10W + (CPU_temp - 50) * 0.1

        Args:
            cpu_temp: Current CPU temperature

        Returns:
            Estimated TDP in watts
        """
        base_tdp = 10.0
        temp_factor = max(0, (cpu_temp - 50) * 0.1)
        return min(15.0, base_tdp + temp_factor)

    def export_dossier(self, output_path: Path):
        """
        Generate human-readable .txt dossier.

        Format:
        - Executive summary (avg TPS, peak temp, total energy, etc.)
        - Session records (all 25 metrics in 5 sections)

        Args:
            output_path: Destination file path
        """
        try:
            # Get summary stats
            stats = self.db.get_summary_stats()

            # Get last 100 sessions
            records = self.db.get_heatmap_data(hours=48)[:100]

            with open(output_path, 'w') as f:
                # Header
                f.write("=" * 80 + "\n")
                f.write("DECKYNEWS FORENSIC DOSSIER\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"Total Sessions: {stats.get('total_sessions', 0)}\n")
                f.write("=" * 80 + "\n\n")

                # Executive summary
                f.write("EXECUTIVE SUMMARY\n")
                f.write("-" * 17 + "\n")
                f.write(f"Average TPS:        {stats.get('avg_tps', 0):.1f} tokens/sec\n")
                f.write(f"Peak CPU Temp:      {stats.get('peak_temp', 0):.1f}°C\n")
                f.write(f"Total Energy:       {stats.get('total_energy', 0):.1f} mWh\n")
                f.write(f"Avg Flesch Score:   {stats.get('avg_flesch', 0):.1f}\n")
                f.write(f"Total Tokens:       {stats.get('total_tokens', 0):,}\n")

                # Session records
                f.write("\n\nSESSION RECORDS\n")
                f.write("-" * 15 + "\n\n")

                for idx, record in enumerate(records, 1):
                    timestamp = datetime.fromtimestamp(record['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"[Session #{idx}] {timestamp}\n")

                    # I. AI Performance
                    f.write("  I. AI PERFORMANCE\n")
                    f.write(f"    • TPS:              {record.get('tps', 0) or 0:.1f} tokens/sec\n")
                    f.write(f"    • TTFT:             {record.get('ttft', 0) or 0:.0f} ms\n")
                    f.write(f"    • Prompt Eval:      {record.get('prompt_eval_time', 0) or 0:.0f} ms\n")
                    f.write(f"    • Total Tokens:     {record.get('total_tokens', 0) or 0}\n")
                    f.write(f"    • Stop Reason:      {record.get('stop_reason') or 'N/A'}\n")
                    f.write(f"    • RAM Delta:        {record.get('ram_delta_mb', 0) or 0:+.0f} MB\n")
                    f.write(f"    • Load Duration:    {record.get('load_duration', 0) or 0:.1f} s\n\n")

                    # II. Hardware & Thermals
                    f.write("  II. HARDWARE & THERMALS\n")
                    f.write(f"    • CPU Peak:         {record.get('cpu_peak_temp', 0) or 0:.1f}°C\n")
                    f.write(f"    • Temp Delta:       {record.get('temp_delta', 0) or 0:+.1f}°C\n")
                    f.write(f"    • TDP:              {record.get('tdp_watts', 0) or 0:.1f} W\n")
                    f.write(f"    • Fan RPM:          {record.get('fan_rpm', 0) or 0:,} RPM\n")
                    f.write(f"    • Energy Cost:      {record.get('energy_mwh', 0) or 0:.2f} mWh\n")
                    f.write(f"    • Cooldown Vel:     {record.get('cooldown_vel', 0) or 0:.2f}°C/s\n\n")

                    # III. Article Metadata
                    f.write("  III. ARTICLE METADATA\n")
                    f.write(f"    • Compression:      {record.get('comp_ratio', 0) or 0:.1f}:1\n")
                    f.write(f"    • Flesch Score:     {record.get('flesch_score', 0) or 0:.1f}\n")
                    f.write(f"    • Duplicates:       {record.get('dup_count', 0) or 0}\n")
                    f.write(f"    • Dedup Latency:    {record.get('dedup_lat', 0) or 0:.3f} s\n")
                    f.write(f"    • TTL:              {record.get('ttl_days', 0) or 0} days\n\n")

                    # IV. Network & Source
                    f.write("  IV. NETWORK & SOURCE\n")
                    f.write(f"    • Fetch Latency:    {record.get('fetch_lat', 0) or 0:.2f} s\n")
                    f.write(f"    • Source Success:   {record.get('src_success', 0) or 0:.0f}%\n")
                    f.write(f"    • Cloud Bypass:     {record.get('cloud_bypass', 0) or 0:.0f}%\n")
                    f.write(f"    • Download Speed:   {record.get('dl_kbps', 0) or 0:.0f} kbps\n\n")

                    # V. Plugin Orchestration
                    f.write("  V. PLUGIN ORCHESTRATION\n")
                    f.write(f"    • IPC Latency:      {record.get('ipc_lat', 0) or 0:.3f} s\n")
                    f.write(f"    • Press Duration:   {record.get('press_dur', 0) or 0:.2f} s\n")
                    f.write(f"    • UI FPS Drop:      {record.get('ui_fps_drop', 0) or 0} frames\n\n")

                # Footer
                f.write("\n" + "=" * 80 + "\n")
                f.write("END OF DOSSIER\n")
                f.write("=" * 80 + "\n")

            self.logger.info(f"Telemetry dossier exported to {output_path}")

        except Exception as e:
            self.logger.error(f"Failed to export dossier: {e}")
            raise

    def shutdown(self):
        """Graceful shutdown."""
        if self._idle_timer:
            self._idle_timer.cancel()
        self.db.shutdown()
