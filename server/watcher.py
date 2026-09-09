import os
import sys
import time
import sqlite3
import datetime
import difflib
import argparse
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure numpy pre-import for DSPy compatibility
import numpy
import dspy
import pathspec
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich import print as rprint

from core.router import ModelRouter

console = Console()

# --- 1. SIGNATURES ---

class SecurityAuditorSig(dspy.Signature):
    """
    Examine Python source code for security vulnerabilities such as:
    SQL injection, hardcoded secrets, unsafe eval/exec, insecure deserialization, 
    path traversal, and unauthorized system command execution.
    """
    code: str = dspy.InputField(desc="The Python source code to audit")
    is_safe: str = dspy.OutputField(desc="Output 'True' if code has no vulnerabilities, otherwise 'False'")
    risk_level: str = dspy.OutputField(desc="Risk level: None, Low, Medium, High, Critical")
    vulnerability_report: str = dspy.OutputField(desc="Clear summary of identified vulnerabilities or 'None'")


class CodeLinterSig(dspy.Signature):
    """
    Examine Python source code for style, hygiene, PEP 8 conventions,
    missing docstrings, bare exceptions, and unused/dead code blocks.
    """
    code: str = dspy.InputField(desc="The Python source code to lint")
    is_clean: str = dspy.OutputField(desc="Output 'True' if clean and compliant, otherwise 'False'")
    lint_violations: str = dspy.OutputField(desc="Bullet points detailing style violations or 'None'")


class CodeFixerSig(dspy.Signature):
    """
    Generate a secure, clean, corrected replacement for the Python code.
    Fix all flagged security flaws and lint violations while preserving 
    the original intended functional behavior and interface.
    Output only the complete, executable Python code.
    """
    original_code: str = dspy.InputField(desc="The source code needing fixes")
    issue_report: str = dspy.InputField(desc="The audit issues and violations to remediate")
    fixed_code: str = dspy.OutputField(desc="Fully corrected, secure Python source code")


# --- 2. MULTI-AGENT PATCH ENGINE ---

class AutonomousPatchEngine(dspy.Module):
    """
    Multi-stage auditing and patching pipeline coordinating Auditor, Linter, and Fixer agents.
    """
    def __init__(self):
        super().__init__()
        self.auditor = dspy.ChainOfThought(SecurityAuditorSig)
        self.linter = dspy.ChainOfThought(CodeLinterSig)
        self.fixer = dspy.ChainOfThought(CodeFixerSig)

    def sanitize_code_output(self, raw_code: str) -> str:
        """Thoroughly strip markdown code fences, headers, and commentary."""
        import re
        code = raw_code.strip()
        
        # Match fenced code blocks like ```python ... ``` or ```py ... ``` or ``` ... ```
        pattern = r"```(?:python|py)?\s*\n([\s\S]*?)\n```"
        matches = re.findall(pattern, code, re.MULTILINE)
        if matches:
            # Pick the largest code block found
            code = max(matches, key=len).strip()
        else:
            # Fallback simple strip if fences are malformed
            if code.startswith("```python"):
                code = code[len("```python"):].strip()
            elif code.startswith("```py"):
                code = code[len("```py"):].strip()
            elif code.startswith("```"):
                code = code[len("```"):].strip()
            if code.endswith("```"):
                code = code[:-3].strip()
        return code

    def scan_and_patch(self, code_content: str) -> Dict[str, Any]:
        """
        Execute security audit followed by lint inspection, generating patches if needed.
        """
        # Step 1: Security Audit
        audit_res = self.auditor(code=code_content)
        is_safe = "true" in str(audit_res.is_safe).lower()
        risk = getattr(audit_res, "risk_level", "None").strip()
        vuln_desc = getattr(audit_res, "vulnerability_report", "None").strip()

        if not is_safe and vuln_desc.lower() != "none":
            # Security vulnerability detected -> trigger Fixer
            fix_res = self.fixer(original_code=code_content, issue_report=f"[SECURITY VULNERABILITY]: {vuln_desc}")
            fixed = self.sanitize_code_output(fix_res.fixed_code)
            return {
                "needs_patch": True,
                "type": "security",
                "risk_level": risk,
                "report": vuln_desc,
                "original_code": code_content,
                "patched_code": fixed
            }

        # Step 2: Code Quality / Lint Scan
        lint_res = self.linter(code=code_content)
        is_clean = "true" in str(lint_res.is_clean).lower()
        lint_desc = getattr(lint_res, "lint_violations", "None").strip()

        if not is_clean and lint_desc.lower() != "none":
            # Style or hygiene issues -> trigger Fixer
            fix_res = self.fixer(original_code=code_content, issue_report=f"[LINT VIOLATION]: {lint_desc}")
            fixed = self.sanitize_code_output(fix_res.fixed_code)
            return {
                "needs_patch": True,
                "type": "lint",
                "risk_level": "Low",
                "report": lint_desc,
                "original_code": code_content,
                "patched_code": fixed
            }

        return {
            "needs_patch": False,
            "type": "clean",
            "risk_level": "None",
            "report": "Code passed security and quality audit.",
            "original_code": code_content,
            "patched_code": code_content
        }


# --- 3. AUDIT & PATCH STAGING DATABASE ---

DB_PATH = "/home/nadir/agent_engine/data/audit_sentry.db"

def init_db(db_path: str = DB_PATH):
    """Initialize SQLite table for staging patches and tracking audit history."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_patches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                patch_type TEXT NOT NULL,
                risk_level TEXT,
                report TEXT,
                original_code TEXT,
                patched_code TEXT
            )
        """)
        conn.commit()

def stage_patch_record(file_path: str, patch_type: str, risk_level: str, report: str, original_code: str, patched_code: str, status: str = "staged", db_path: str = DB_PATH) -> int:
    """Store patch into the staging database."""
    init_db(db_path)
    now_iso = datetime.datetime.now().isoformat()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_patches (file_path, timestamp, status, patch_type, risk_level, report, original_code, patched_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (file_path, now_iso, status, patch_type, risk_level, report, original_code, patched_code))
        conn.commit()
        return cursor.lastrowid

def get_staged_patches(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve all pending staged patches."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_patches WHERE status = 'staged' ORDER BY id DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]

def apply_staged_patch(patch_id: int, db_path: str = DB_PATH) -> bool:
    """Apply a staged patch to the target file on disk."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_patches WHERE id = ?", (patch_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        file_path = row["file_path"]
        patched_code = row["patched_code"]
        
        # Write patched code to disk
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(patched_code)
            
        cursor.execute("UPDATE audit_patches SET status = 'applied' WHERE id = ?", (patch_id,))
        conn.commit()
        return True

def reject_staged_patch(patch_id: int, db_path: str = DB_PATH) -> bool:
    """Mark a staged patch as rejected."""
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE audit_patches SET status = 'rejected' WHERE id = ?", (patch_id,))
        conn.commit()
        return cursor.rowcount > 0


# --- 4. FILE FILTERING & AGENTIGNORE ---

def get_ignore_spec(root_dir: str = "/home/nadir/agent_engine") -> Optional[pathspec.PathSpec]:
    """Parse .agentignore file rules."""
    ignore_file = os.path.join(root_dir, ".agentignore")
    if not os.path.exists(ignore_file):
        return None
    with open(ignore_file, "r", encoding="utf-8") as f:
        return pathspec.PathSpec.from_lines("gitignore", f.readlines())

def should_ignore_file(file_path: str, root_dir: str = "/home/nadir/agent_engine", spec: Optional[pathspec.PathSpec] = None) -> bool:
    """Check if file matches .agentignore exclusion rules."""
    if spec is None:
        spec = get_ignore_spec(root_dir)
    if spec is None:
        return False
    try:
        rel_path = os.path.relpath(file_path, root_dir)
        return spec.match_file(rel_path)
    except Exception:
        return False


# --- 5. SENTRY WATCHDOG EVENT HANDLER ---

class SentryWatchHandler(FileSystemEventHandler):
    """
    Watches for file modifications, evaluates ignore rules, and runs the AutonomousPatchEngine.
    """
    def __init__(self, root_dir: str, auto_apply: bool = False, db_path: str = DB_PATH):
        super().__init__()
        self.root_dir = root_dir
        self.auto_apply = auto_apply
        self.db_path = db_path
        self.last_runs: Dict[str, float] = {}
        self.auto_apply_history: Dict[str, List[float]] = {}
        self.locked_files: set = set()
        self.engine = AutonomousPatchEngine()
        self.ignore_spec = get_ignore_spec(root_dir)
        init_db(self.db_path)

    def on_modified(self, event):
        if event.is_directory:
            return

        file_path = event.src_path
        if not file_path.endswith(".py"):
            return

        # Debounce rapid file writes (3 seconds per file)
        now = time.time()
        if file_path in self.last_runs and (now - self.last_runs[file_path]) < 3.0:
            return

        # Check .agentignore
        if should_ignore_file(file_path, self.root_dir, self.ignore_spec):
            return

        self.last_runs[file_path] = now
        self.process_file(file_path)

    def process_file(self, file_path: str):
        """Perform audit and patch generation."""
        console.print(f"\n[bold cyan]🔍 [Sentry][/bold cyan] Scanning modified file: [yellow]{file_path}[/yellow]...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()
        except Exception as e:
            console.print(f"[red]Error reading file {file_path}: {e}[/red]")
            return

        # Execute Engine
        try:
            result = self.engine.scan_and_patch(code_content)
        except Exception as e:
            console.print(f"[bold red]❌ Sentry Agent processing error:[/bold red] {e}")
            return

        if not result["needs_patch"]:
            console.print(f"[bold green]✅ [Sentry Clean][/bold green] {file_path} passed all security and quality checks.")
            return

        # Vulnerability / Violation Flagged
        patch_type = result["type"].upper()
        risk = result["risk_level"]
        report = result["report"]
        patched_code = result["patched_code"]

        console.print(Panel(
            f"[bold red]⚠️ {patch_type} ALERT[/bold red] | Risk Level: [bold yellow]{risk}[/bold yellow]\n"
            f"[white]{report}[/white]",
            title=f"[bold]Sentry Intercept: {os.path.basename(file_path)}[/bold]",
            border_style="red" if risk in ["High", "Critical"] else "yellow"
        ))

        # Generate Diff
        diff_lines = list(difflib.unified_diff(
            code_content.splitlines(keepends=True),
            patched_code.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(file_path)}",
            tofile=f"b/{os.path.basename(file_path)}"
        ))
        diff_text = "".join(diff_lines)
        if diff_text:
            console.print(Syntax(diff_text, "diff", theme="monokai", line_numbers=True))

        if self.auto_apply:
            now_ts = time.time()
            # Sliding window: keep timestamps within the last 15 seconds
            history = [t for t in self.auto_apply_history.get(file_path, []) if (now_ts - t) < 15.0]

            if file_path in self.locked_files or len(history) >= 3:
                self.locked_files.add(file_path)
                console.print(Panel(
                    f"[bold red]🛑 INFINITE LOOP BREAKER ACTIVATED[/bold red]\n"
                    f"File '{os.path.basename(file_path)}' triggered > 3 automatic modifications in 15 seconds.\n"
                    f"Auto-apply has been paused for this file. Patch staged into database for manual review.",
                    border_style="red"
                ))
                patch_id = stage_patch_record(file_path, result["type"], risk, f"[LOOP_BREAKER] {report}", code_content, patched_code, status="staged", db_path=self.db_path)
                console.print(f"[bold yellow]📥 [Sentry Staged][/bold yellow] Patch #{patch_id} safely staged for review via Dashboard.")
                return

            history.append(now_ts)
            self.auto_apply_history[file_path] = history

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(patched_code)
            stage_patch_record(file_path, result["type"], risk, report, code_content, patched_code, status="auto_applied", db_path=self.db_path)
            console.print(f"[bold green]✨ [Sentry Auto-Applied][/bold green] Remediation written directly to [yellow]{file_path}[/yellow].")
        else:
            patch_id = stage_patch_record(file_path, result["type"], risk, report, code_content, patched_code, status="staged", db_path=self.db_path)
            console.print(f"[bold blue]📥 [Sentry Staged][/bold blue] Patch #{patch_id} stored in database for review. (Run with `--auto-apply` or approve via Dashboard).")


# --- 6. CLI ENTRYPOINT ---

def start_watcher(watch_dir: str = "/home/nadir/agent_engine", auto_apply: bool = False, db_path: str = DB_PATH):
    """Initialize watchdog observer and start monitoring."""
    router = ModelRouter()
    lm, label = router.initialize_and_configure()
    
    console.print(Panel.fit(
        f"[bold cyan]🛡️ Code Sentry / File-Watcher Active[/bold cyan]\n"
        f"Watching Directory: [yellow]{watch_dir}[/yellow]\n"
        f"Active Model: [green]{label}[/green]\n"
        f"Mode: [{'green]Auto-Apply' if auto_apply else 'blue]Stage for Approval'}[/]",
        border_style="cyan"
    ))

    event_handler = SentryWatchHandler(root_dir=watch_dir, auto_apply=auto_apply, db_path=db_path)
    observer = Observer()
    observer.schedule(event_handler, path=watch_dir, recursive=True)
    observer.start()

    console.print("[dim]Listening for filesystem changes... Press Ctrl+C to terminate.[/dim]\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping Sentry Watcher...[/yellow]")
        observer.stop()
    observer.join()

def main():
    parser = argparse.ArgumentParser(description="Code Sentry & File Watcher Daemon")
    parser.add_argument("--dir", default="/home/nadir/agent_engine", help="Directory path to monitor")
    parser.add_argument("--auto-apply", action="store_true", help="Automatically write patches to disk on detection")
    parser.add_argument("--list-staged", action="store_true", help="List all pending staged patches")
    parser.add_argument("--apply", type=int, help="Apply specific staged patch ID")
    parser.add_argument("--reject", type=int, help="Reject specific staged patch ID")

    args = parser.parse_args()

    if args.list_staged:
        patches = get_staged_patches()
        if not patches:
            console.print("[green]No pending staged patches in database.[/green]")
            return
        table = Table(title="Pending Staged Patches", header_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("File", style="yellow")
        table.add_column("Type", style="bold")
        table.add_column("Risk", style="red")
        table.add_column("Timestamp", style="dim")
        for p in patches:
            table.add_row(str(p["id"]), os.path.basename(p["file_path"]), p["patch_type"], p["risk_level"] or "N/A", p["timestamp"])
        console.print(table)
    elif args.apply is not None:
        success = apply_staged_patch(args.apply)
        if success:
            console.print(f"[bold green]Successfully applied patch #{args.apply}![/bold green]")
        else:
            console.print(f"[bold red]Failed to find or apply patch #{args.apply}[/bold red]")
    elif args.reject is not None:
        success = reject_staged_patch(args.reject)
        if success:
            console.print(f"[bold yellow]Marked patch #{args.reject} as rejected.[/bold yellow]")
        else:
            console.print(f"[bold red]Failed to find patch #{args.reject}[/bold red]")
    else:
        start_watcher(watch_dir=args.dir, auto_apply=args.auto_apply)

if __name__ == "__main__":
    main()
