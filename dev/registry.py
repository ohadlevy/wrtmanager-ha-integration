#!/usr/bin/env python3
"""Pipeline run registry backed by SQLite.

Tracks all work-issue.sh runs: status, review verdicts, resume context.
Used by sessions.sh CLI and (future) web UI.

Usage from scripts:
    python dev/registry.py create --issue 128 --branch feature/...
    python dev/registry.py update <run_id> --status fail
    python dev/registry.py list [--status running|pass|fail]
    python dev/registry.py get <run_id>
    python dev/registry.py resume-context --issue <number>
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / ".claude" / "runs.db"


def get_db() -> sqlite3.Connection:
    """Get database connection, creating schema if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_number INTEGER NOT NULL,
            issue_title TEXT,
            issue_body TEXT,
            branch_name TEXT,
            worktree_path TEXT,
            model TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            log_file TEXT,
            ha_url TEXT,
            ha_port INTEGER,
            mock_pid INTEGER,
            diff_stat TEXT,
            pr_number INTEGER,
            pr_url TEXT,
            review_verdict TEXT,
            review_feedback TEXT,
            cost_estimate REAL,
            resume_context TEXT,
            error_message TEXT
        )
    """
    )
    conn.commit()
    return conn


def create_run(args) -> int:
    """Create a new run entry, return run ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO runs (
                issue_number, issue_title, issue_body,
                branch_name, worktree_path, model,
                status, started_at, log_file,
                ha_url, ha_port, mock_pid)
           VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)""",
        (
            args.issue,
            getattr(args, "issue_title", ""),
            getattr(args, "issue_body", ""),
            args.branch,
            args.worktree,
            args.model,
            datetime.now(timezone.utc).isoformat(),
            args.log,
            args.ha_url,
            args.ha_port,
            args.mock_pid,
        ),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    print(run_id)
    return run_id


def update_run(args):
    """Update fields on an existing run."""
    conn = get_db()
    updates = []
    values = []

    for field in [
        "status",
        "issue_title",
        "issue_body",
        "diff_stat",
        "review_verdict",
        "review_feedback",
        "pr_number",
        "pr_url",
        "cost_estimate",
        "error_message",
        "ha_url",
        "ha_port",
        "mock_pid",
    ]:
        val = getattr(args, field.replace("-", "_"), None)
        if val is not None:
            updates.append(f"{field} = ?")
            values.append(val)

    if args.status in ("pass", "fail", "error"):
        updates.append("finished_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())

    # Build resume context on failure
    if args.status == "fail" and args.review_feedback:
        run = dict(conn.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone())
        resume = {
            "issue_number": run["issue_number"],
            "review_verdict": args.review_verdict or run.get("review_verdict"),
            "review_feedback": args.review_feedback,
            "worktree_path": run["worktree_path"],
            "ha_url": run["ha_url"],
        }
        updates.append("resume_context = ?")
        values.append(json.dumps(resume))

    if updates:
        values.append(args.run_id)
        conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", values)
        conn.commit()
    conn.close()


def list_runs(args):
    """List runs, optionally filtered by status."""
    conn = get_db()
    query = "SELECT * FROM runs"
    params = []
    if args.status:
        query += " WHERE status = ?"
        params.append(args.status)
    if args.issue:
        query += " WHERE" if "WHERE" not in query else " AND"
        query += " issue_number = ?"
        params.append(args.issue)
    query += " ORDER BY id DESC"
    if args.limit:
        query += " LIMIT ?"
        params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return

    if not rows:
        print("No runs found.")
        return

    # Table format
    print(f"{'ID':>4}  {'Issue':>5}  {'Status':<8}  {'Review':<14}  {'Started':<20}  {'Branch'}")
    print("-" * 90)
    for r in rows:
        started = r["started_at"][:19].replace("T", " ") if r["started_at"] else ""
        verdict = r["review_verdict"] or ""
        branch = r["branch_name"] or ""
        if len(branch) > 30:
            branch = "..." + branch[-27:]
        row_str = (
            f"{r['id']:>4}  #{r['issue_number']:<4}  "
            f"{r['status']:<8}  {verdict:<14}  "
            f"{started:<20}  {branch}"
        )
        print(row_str)


def get_run(args):
    """Get full details of a single run."""
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
    conn.close()
    if not row:
        print(f"Run {args.run_id} not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(dict(row), indent=2))


def get_field(args):
    """Get a single field from a run by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
    conn.close()
    if not row:
        sys.exit(1)
    val = dict(row).get(args.field, "")
    print(val if val else "")


def resume_context(args):
    """Get resume context for a failed run, or build it from current state."""
    conn = get_db()

    # Find by run_id or latest for issue
    if args.run_id:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (args.run_id,)).fetchone()
    elif args.issue:
        row = conn.execute(
            "SELECT * FROM runs WHERE issue_number = ? ORDER BY id DESC LIMIT 1",
            (args.issue,),
        ).fetchone()
    else:
        print("Specify --run-id or --issue", file=sys.stderr)
        sys.exit(1)

    conn.close()
    if not row:
        print("Run not found", file=sys.stderr)
        sys.exit(1)

    run = dict(row)

    # Build context from stored data
    ctx = {
        "issue_number": run["issue_number"],
        "issue_title": run.get("issue_title", ""),
        "issue_body": run.get("issue_body", ""),
        "review_verdict": run.get("review_verdict"),
        "review_feedback": run.get("review_feedback"),
        "diff_stat": run.get("diff_stat", ""),
        "worktree_path": run["worktree_path"],
        "ha_url": run.get("ha_url"),
    }

    # Merge any stored resume_context
    if run.get("resume_context"):
        stored = json.loads(run["resume_context"])
        ctx.update(stored)

    issue_section = ""
    if ctx.get("issue_title"):
        title = ctx["issue_title"]
        body = ctx.get("issue_body", "")
        num = ctx["issue_number"]
        issue_section = f"\n## Issue #{num}: {title}\n{body}\n"

    diff_section = ""
    if ctx.get("diff_stat"):
        diff_section = f"\n## Changes so far\n{ctx['diff_stat']}\n"

    # Build a prompt for resuming
    prompt = f"""You are resuming work on issue #{ctx['issue_number']} after a failed review.

Working directory: {ctx['worktree_path']}
{issue_section}{diff_section}
## Previous review verdict: {ctx.get('review_verdict', 'N/A')}
{ctx.get('review_feedback', 'No feedback available.')}

## Instructions
1. Read the review feedback above carefully
2. Look at the screenshots in .test-screenshots/ to understand the visual issues
3. Fix the identified problems with minimal changes
4. Run tests: PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
5. Commit your fixes
"""
    if args.prompt:
        print(prompt)
    else:
        print(json.dumps(ctx, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Pipeline run registry")
    sub = parser.add_subparsers(dest="command")

    # create
    p = sub.add_parser("create")
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--issue-title", default="")
    p.add_argument("--issue-body", default="")
    p.add_argument("--branch", default="")
    p.add_argument("--worktree", default="")
    p.add_argument("--model", default="")
    p.add_argument("--log", default="")
    p.add_argument("--ha-url", default="")
    p.add_argument("--ha-port", type=int, default=0)
    p.add_argument("--mock-pid", type=int, default=0)

    # update
    p = sub.add_parser("update")
    p.add_argument("run_id", type=int)
    p.add_argument("--status")
    p.add_argument("--issue-title")
    p.add_argument("--issue-body")
    p.add_argument("--diff-stat")
    p.add_argument("--review-verdict")
    p.add_argument("--review-feedback")
    p.add_argument("--pr-number", type=int)
    p.add_argument("--pr-url")
    p.add_argument("--cost-estimate", type=float)
    p.add_argument("--error-message")
    p.add_argument("--ha-url")
    p.add_argument("--ha-port", type=int)
    p.add_argument("--mock-pid", type=int)

    # list
    p = sub.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--issue", type=int)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")

    # get
    p = sub.add_parser("get")
    p.add_argument("run_id", type=int)

    # get-field
    p = sub.add_parser("get-field")
    p.add_argument("run_id", type=int)
    p.add_argument("field")

    # resume-context
    p = sub.add_parser("resume-context")
    p.add_argument("--run-id", type=int)
    p.add_argument("--issue", type=int)
    p.add_argument("--prompt", action="store_true", help="Output as Claude prompt")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    {
        "create": create_run,
        "update": update_run,
        "list": list_runs,
        "get": get_run,
        "get-field": get_field,
        "resume-context": resume_context,
    }[args.command](args)


if __name__ == "__main__":
    main()
