import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path, PureWindowsPath
from tkinter import END, StringVar, Tk
from tkinter import scrolledtext, ttk

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = r"C:\dev\jd_data.db"
DEFAULT_SITE = "jobkorea"
SUPPORTED_SITES = ("jobkorea", "saramin")


def _resolve_path(raw_path: str) -> Path:
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive.lower() == "c:":
        if Path("C:/").exists():
            return Path(windows_path)
        return Path("/mnt/c", *windows_path.parts[1:])
    return Path(raw_path)


def _read_env() -> None:
    load_dotenv(BASE_DIR / ".env")


def _get_db_path() -> str:
    return os.getenv("JD_DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH


def _find_python_executable() -> str:
    candidates = [
        BASE_DIR / ".venv" / "Scripts" / "python.exe",
        BASE_DIR / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _fetch_db_counts() -> dict[str, int | str]:
    resolved_db_path = _resolve_path(_get_db_path())
    if not resolved_db_path.exists():
        return {
            "total_postings": 0,
            "classified_postings": 0,
            "job_criteria_count": 0,
            "job_family_status_line": "직무별 분류: 없음",
            "job_family_telegram_line": "없음",
        }

    conn = sqlite3.connect(resolved_db_path)
    try:
        total_postings = int(conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0])
        classified_postings = int(
            conn.execute(
                "SELECT COUNT(*) FROM job_postings WHERE classification_status = 'classified'"
            ).fetchone()[0]
        )
        job_criteria_count = int(conn.execute("SELECT COUNT(*) FROM job_criteria").fetchone()[0])
        family_rows = conn.execute(
            """
            SELECT job_family, COUNT(DISTINCT job_id) AS job_count
            FROM job_tags
            GROUP BY job_family
            ORDER BY job_count DESC, job_family ASC
            """
        ).fetchall()
        family_parts = [f"{job_family}: {job_count}개" for job_family, job_count in family_rows]
        return {
            "total_postings": total_postings,
            "classified_postings": classified_postings,
            "job_criteria_count": job_criteria_count,
            "job_family_status_line": "직무별 분류: " + (" | ".join(family_parts) if family_parts else "없음"),
            "job_family_telegram_line": ", ".join(family_parts) if family_parts else "없음",
        }
    finally:
        conn.close()


def _send_telegram_message(message: str) -> tuple[bool, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False, "telegram env missing"

    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url=f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
        return True, body


class CollectorGUI:
    def __init__(self, root: Tk) -> None:
        _read_env()

        self.root = root
        self.root.title("jd-collector-agent GUI")
        self.root.geometry("980x760")

        self.python_exec = _find_python_executable()
        self.event_queue: queue.Queue[tuple] = queue.Queue()
        self.current_process: subprocess.Popen[str] | None = None
        self.is_running = False

        self.site_var = StringVar(value=DEFAULT_SITE)
        self.keyword_var = StringVar()
        self.target_count_var = StringVar(value="10")
        self.db_status_var = StringVar()
        self.run_status_var = StringVar(value="대기 중")

        self._build_ui()
        self.refresh_db_status()
        self.root.after(100, self._drain_event_queue)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        status_frame = ttk.LabelFrame(frame, text="DB 현황", padding=12)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, textvariable=self.db_status_var).pack(anchor="w")

        input_frame = ttk.LabelFrame(frame, text="수집 입력", padding=12)
        input_frame.pack(fill="x", pady=(12, 0))
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(input_frame, text="사이트").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.site_combo = ttk.Combobox(
            input_frame,
            textvariable=self.site_var,
            values=SUPPORTED_SITES,
            state="readonly",
            width=16,
        )
        self.site_combo.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(input_frame, text="검색어").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.keyword_entry = ttk.Entry(input_frame, textvariable=self.keyword_var)
        self.keyword_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(input_frame, text="목표 수").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.target_count_entry = ttk.Entry(input_frame, textvariable=self.target_count_var, width=16)
        self.target_count_entry.grid(row=2, column=1, sticky="w", pady=4)

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(12, 0))

        self.collect_button = ttk.Button(button_frame, text="수집 시작", command=self.start_collect)
        self.collect_button.pack(side="left")

        self.classify_button = ttk.Button(button_frame, text="직무 분류", command=self.start_classify)
        self.classify_button.pack(side="left", padx=(8, 0))

        self.analyze_button = ttk.Button(button_frame, text="역량 분석", command=self.start_analyze)
        self.analyze_button.pack(side="left", padx=(8, 0))

        ttk.Label(button_frame, textvariable=self.run_status_var).pack(side="right")

        log_frame = ttk.LabelFrame(frame, text="로그", padding=12)
        log_frame.pack(fill="both", expand=True, pady=(12, 0))

        self.log_widget = scrolledtext.ScrolledText(log_frame, wrap="word", height=28, state="disabled")
        self.log_widget.pack(fill="both", expand=True)

    def append_log(self, message: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert(END, message)
        self.log_widget.see(END)
        self.log_widget.configure(state="disabled")

    def refresh_db_status(self) -> None:
        try:
            counts = _fetch_db_counts()
            self.db_status_var.set(
                "전체 공고 수: {total_postings} | classified 수: {classified_postings} | "
                "job_criteria 수: {job_criteria_count}\n"
                "{job_family_status_line}".format(**counts)
            )
        except Exception as err:
            self.db_status_var.set(f"DB 현황 조회 실패: {err}")

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.collect_button.configure(state=state)
        self.classify_button.configure(state=state)
        self.analyze_button.configure(state=state)
        self.site_combo.configure(state="readonly" if enabled else "disabled")
        self.keyword_entry.configure(state=state)
        self.target_count_entry.configure(state=state)

    def start_collect(self) -> None:
        if self.is_running:
            return

        site_name = self.site_var.get().strip()
        search_keyword = self.keyword_var.get().strip()
        target_count_text = self.target_count_var.get().strip()

        if site_name not in SUPPORTED_SITES:
            self.append_log("[WARN] site_name must be jobkorea or saramin\n")
            return
        if not search_keyword:
            self.append_log("[WARN] search_keyword is required\n")
            return
        if not target_count_text.isdigit() or int(target_count_text) <= 0:
            self.append_log("[WARN] target_count must be a positive integer\n")
            return

        stdin_payload = f"{site_name}\n{search_keyword}\n{target_count_text}\n\n"
        context = {
            "site_name": site_name,
            "search_keyword": search_keyword,
            "target_count": target_count_text,
        }
        self._run_script(
            stage_label="수집 시작",
            command=[self.python_exec, "-u", "src/collect.py"],
            stdin_payload=stdin_payload,
            context=context,
        )

    def start_classify(self) -> None:
        if self.is_running:
            return

        self._run_script(
            stage_label="직무 분류",
            command=[self.python_exec, "-u", "src/classify.py"],
            stdin_payload="\n\n",
            context={"batch_size": "default"},
        )

    def start_analyze(self) -> None:
        if self.is_running:
            return

        self._run_script(
            stage_label="역량 분석",
            command=[self.python_exec, "-u", "src/analyze.py"],
            stdin_payload="\n\n",
            context={"min_sample_count": "default"},
        )

    def _run_script(
        self,
        stage_label: str,
        command: list[str],
        stdin_payload: str,
        context: dict[str, str],
    ) -> None:
        self.is_running = True
        self.set_buttons_enabled(False)
        self.run_status_var.set(f"{stage_label} 실행 중")
        self.append_log(f"\n=== {stage_label} ===\n")
        self.append_log(f"[INFO] command={' '.join(command)}\n")

        thread = threading.Thread(
            target=self._worker_run_script,
            args=(stage_label, command, stdin_payload, context),
            daemon=True,
        )
        thread.start()

    def _worker_run_script(
        self,
        stage_label: str,
        command: list[str],
        stdin_payload: str,
        context: dict[str, str],
    ) -> None:
        started_at = time.time()
        process: subprocess.Popen[str] | None = None
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            process = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            self.current_process = process

            if process.stdin is not None:
                process.stdin.write(stdin_payload)
                process.stdin.close()

            if process.stdout is not None:
                for line in process.stdout:
                    self.event_queue.put(("log", line))

            return_code = process.wait()
        except Exception as err:
            self.event_queue.put(("log", f"[ERROR] {stage_label} 실행 실패: {err}\n"))
            return_code = -1
        finally:
            elapsed = time.time() - started_at
            self.current_process = None
            self.event_queue.put(("done", stage_label, return_code, elapsed, context))

    def _drain_event_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "log":
                self.append_log(event[1])
            elif event_type == "done":
                _, stage_label, return_code, elapsed, context = event
                self._handle_stage_done(stage_label, return_code, elapsed, context)

        self.root.after(100, self._drain_event_queue)

    def _handle_stage_done(
        self,
        stage_label: str,
        return_code: int,
        elapsed: float,
        context: dict[str, str],
    ) -> None:
        self.is_running = False
        self.set_buttons_enabled(True)
        self.refresh_db_status()

        success = return_code == 0
        status_text = "완료" if success else "실패"
        self.run_status_var.set(f"{stage_label} {status_text}")
        self.append_log(f"[INFO] {stage_label} {status_text} (exit_code={return_code}, elapsed={elapsed:.1f}s)\n")

        try:
            counts = _fetch_db_counts()
        except Exception as err:
            counts = {
                "total_postings": -1,
                "classified_postings": -1,
                "job_criteria_count": -1,
            }
            self.append_log(f"[WARN] DB 현황 조회 실패: {err}\n")

        lines = [
            f"[jd-collector-agent] {stage_label} {status_text}",
            f"exit_code={return_code}",
            f"elapsed={elapsed:.1f}s",
            f"전체 공고 수={counts['total_postings']}",
            f"classified 수={counts['classified_postings']}",
            f"job_criteria 수={counts['job_criteria_count']}",
        ]
        if stage_label == "수집 시작":
            lines.append(f"site={context.get('site_name', '')}")
            lines.append(f"keyword={context.get('search_keyword', '')}")
            lines.append(f"target_count={context.get('target_count', '')}")
        if stage_label == "직무 분류":
            lines.append(f"직무별 분류={counts['job_family_telegram_line']}")

        telegram_message = "\n".join(lines)
        try:
            sent, info = _send_telegram_message(telegram_message)
            if sent:
                self.append_log("[INFO] telegram_notification_sent=true\n")
            else:
                self.append_log(f"[WARN] telegram_notification_sent=false reason={info}\n")
        except Exception as err:
            self.append_log(f"[WARN] telegram_notification_sent=false reason={err}\n")


def main() -> None:
    root = Tk()
    CollectorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
