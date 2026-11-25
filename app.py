import json
import os
import re
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "agency.db")


def get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


BOSS_USERNAME = get_secret("BOSS_USERNAME", "boss")
BOSS_PASSWORD = get_secret("BOSS_PASSWORD", "ChangeMe123!")

EMPLOYEES = [
    {"name": "Alex", "role": "Project Manager (Chief of Staff)", "kpi_label": "Tasks Audited / Synced", "kpi_target": 10},
    {"name": "Maya", "role": "Talent & Market Researcher", "kpi_label": "Talent Briefs / Leads", "kpi_target": 6},
    {"name": "Liam", "role": "Resume & Skill Evaluator", "kpi_label": "Candidates Evaluated", "kpi_target": 8},
    {"name": "Elena", "role": "Outreach & Content Writer", "kpi_label": "Posts & Sequences", "kpi_target": 5},
    {"name": "Noah", "role": "Pipeline & Outreach Coordinator", "kpi_label": "Outreach Touches", "kpi_target": 10},
    {"name": "Zoe", "role": "Compliance & Quality Auditor", "kpi_label": "Audits Completed", "kpi_target": 6},
    {"name": "Raj", "role": "Candidate Support & Triage", "kpi_label": "Tickets Resolved", "kpi_target": 8},
    {"name": "Sofia", "role": "Hiring Analytics & KPI Specialist", "kpi_label": "Metric Snapshots", "kpi_target": 4},
]

VALID_STATUSES = ["Queued", "In Progress", "Blocked", "Completed"]
VALID_PRIORITIES = ["Low", "Medium", "High", "Critical"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def sync_to_google_sheet(task_row: dict) -> str:
    sheet_id = get_secret("GOOGLE_SHEETS_ID", "").strip()
    sa_json = get_secret("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not sheet_id or not sa_json:
        return "Local SQLite ledger active (add GOOGLE_SHEETS_ID & GOOGLE_SERVICE_ACCOUNT_JSON in Secrets for live Sheets sync)"

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if sa_json.lstrip().startswith("{"):
            creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(sa_json, scopes=scopes)

        gc = gspread.authorize(creds)
        ws = gc.open_by_key(sheet_id).sheet1
        headers = [
            "Task ID",
            "Timestamp",
            "Assigned By",
            "Agent Name",
            "Task Description",
            "Priority",
            "Status",
            "Output / Result Link",
            "Completion Time",
        ]
        if ws.row_values(1) != headers:
            ws.update("A1:I1", [headers])

        row_values = [
            task_row["task_id"],
            task_row["timestamp"],
            task_row["assigned_by"],
            task_row["agent_name"],
            f"{task_row['title']}: {task_row['description']}".strip(": "),
            task_row["priority"],
            task_row["status"],
            task_row["output_link"] or "",
            task_row["completion_time"] or "",
        ]
        cell = ws.find(task_row["task_id"], in_column=1)
        if cell:
            ws.update(f"A{cell.row}:I{cell.row}", [row_values])
        else:
            ws.append_row(row_values)
        return "Synced to Google Sheet Ledger"
    except Exception as exc:
        return f"Sheet sync fallback ({exc})"


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            assigned_by TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            deadline TEXT,
            output_link TEXT,
            completion_time TEXT,
            blocker_reason TEXT,
            platform TEXT,
            leads_count INTEGER DEFAULT 0,
            posts_count INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_key TEXT NOT NULL,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS report_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT NOT NULL,
            recipient TEXT NOT NULL,
            delivery_status TEXT NOT NULL,
            summary_text TEXT NOT NULL
        )
        """
    )

    if cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0:
        ts = now_iso()
        td = today_str()
        earlier = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        seed_tasks = [
            ("TF-101", ts, "Boss", "Maya", "Source Senior Backend & AI Engineers in Riga/EU",
             "Identify 8 qualified engineering leads with Python and distributed systems backgrounds.",
             "High", "Completed", td, "https://sheets.google.com/talentflow-leads-tf101", ts, "",
             "LinkedIn Recruiter", 8, 0),
            ("TF-102", ts, "Boss", "Elena", "Publish 2 LinkedIn posts on AI hiring workflows",
             "Draft and publish two LinkedIn posts highlighting structured technical evaluation.",
             "Medium", "Completed", td, "https://linkedin.com/posts/talentflow-ai-workflow-demo", ts, "",
             "LinkedIn", 0, 2),
            ("TF-103", ts, "Alex (PM)", "Liam", "Score 12 incoming candidate resumes for Data/AI roles",
             "Evaluate resume fit, project depth, and availability.",
             "High", "In Progress", td, "", "", "", "Internal ATS", 0, 0),
            ("TF-104", ts, "Boss", "Noah", "Launch outbound sequence for Series A startup founders",
             "Send initial outreach batch to 15 hiring leads.",
             "High", "Blocked", td, "", "",
             "Awaiting Zoe's compliance sign-off on outreach domain & opt-out footer.",
             "Email / LinkedIn", 0, 0),
            ("TF-105", ts, "Alex (PM)", "Raj", "Triage 6 applicant and hiring-manager support tickets",
             "Categorize tickets, draft replies, and escalate interview scheduling conflicts.",
             "Medium", "In Progress", td, "", "", "", "Support Desk", 0, 0),
            ("TF-106", earlier, "Boss", "Liam", "Calibrate technical screening rubric for ML Engineers",
             "Finalize scoring criteria and interview prompt bank.",
             "Medium", "Completed", td, "https://docs.example.com/ml-rubric-v2", earlier, "",
             "Notion / Docs", 0, 0),
            ("TF-107", earlier, "Alex (PM)", "Sofia", "Generate weekly funnel & SLA conversion snapshot",
             "Compile weekly metrics across sourcing, screening, and outreach.",
             "Low", "Completed", td, "https://sheets.google.com/talentflow-weekly-kpi", earlier, "",
             "Analytics", 0, 0),
        ]
        cur.executemany(
            """
            INSERT INTO tasks (
                task_id, timestamp, assigned_by, agent_name, title, description,
                priority, status, deadline, output_link, completion_time,
                blocker_reason, platform, leads_count, posts_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            seed_tasks,
        )
    conn.commit()
    conn.close()


def next_task_id(conn) -> str:
    row = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()
    num = 101 + int(row["c"])
    while conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (f"TF-{num}",)).fetchone():
        num += 1
    return f"TF-{num}"


def create_task_record(
    title: str,
    description: str,
    agent_name: str,
    priority: str = "Medium",
    deadline: str | None = None,
    assigned_by: str = "Boss",
    status: str = "In Progress",
    platform: str = "Dashboard",
    leads_count: int = 0,
    posts_count: int = 0,
    blocker_reason: str = "",
) -> dict:
    valid_agents = {e["name"] for e in EMPLOYEES}
    if agent_name not in valid_agents:
        agent_name = "Alex"
    if priority not in VALID_PRIORITIES:
        priority = "Medium"
    if status not in VALID_STATUSES:
        status = "In Progress"
    if not deadline:
        deadline = today_str()

    ts = now_iso()
    completion_time = ts if status == "Completed" else ""
    output_link = f"https://outputs.talentflow.local/{agent_name.lower()}/{ts[:10]}" if status == "Completed" else ""

    conn = get_db()
    tid = next_task_id(conn)
    conn.execute(
        """
        INSERT INTO tasks (
            task_id, timestamp, assigned_by, agent_name, title, description,
            priority, status, deadline, output_link, completion_time,
            blocker_reason, platform, leads_count, posts_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tid, ts, assigned_by, agent_name, title.strip(),
            description.strip() or title.strip(), priority, status, deadline,
            output_link, completion_time, blocker_reason.strip(), platform,
            int(leads_count), int(posts_count),
        ),
    )
    conn.commit()
    row = dict(conn.execute("SELECT * FROM tasks WHERE task_id = ?", (tid,)).fetchone())
    conn.close()
    row["sheet_sync"] = sync_to_google_sheet(row)
    return row


def update_task_status(task_id: str, new_status: str, blocker_reason: str = "", output_link: str = "") -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return None
    completion_time = row["completion_time"]
    final_link = output_link.strip() or row["output_link"]
    if new_status == "Completed":
        if not completion_time:
            completion_time = now_iso()
        if not final_link:
            final_link = f"https://outputs.talentflow.local/{task_id.lower()}"
    else:
        completion_time = ""

    conn.execute(
        "UPDATE tasks SET status = ?, blocker_reason = ?, output_link = ?, completion_time = ? WHERE task_id = ?",
        (new_status, blocker_reason.strip(), final_link, completion_time, task_id),
    )
    conn.commit()
    updated = dict(conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone())
    conn.close()
    updated["sheet_sync"] = sync_to_google_sheet(updated)
    return updated


def compute_reports_data():
    conn = get_db()
    tasks = [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()]
    conn.close()

    td = today_str()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    per_employee = []
    for emp in EMPLOYEES:
        name = emp["name"]
        emp_tasks = [t for t in tasks if t["agent_name"] == name]
        completed = [t for t in emp_tasks if t["status"] == "Completed"]
        pending = [t for t in emp_tasks if t["status"] in ("Queued", "In Progress", "Blocked")]
        blocked = [t for t in emp_tasks if t["status"] == "Blocked"]
        active_tasks = [t for t in emp_tasks if t["status"] == "In Progress"]
        today_done = [t for t in completed if (t["completion_time"] or t["timestamp"]).startswith(td)]
        week_done = [t for t in completed if (t["completion_time"] or t["timestamp"]) >= week_ago]

        durations = []
        for t in completed:
            if t.get("completion_time") and t.get("timestamp"):
                try:
                    dt_s = datetime.strptime(t["timestamp"], "%Y-%m-%d %H:%M:%S")
                    dt_e = datetime.strptime(t["completion_time"], "%Y-%m-%d %H:%M:%S")
                    durations.append(max(0.05, (dt_e - dt_s).total_seconds() / 3600.0))
                except ValueError:
                    pass
        avg_hrs = round(sum(durations) / len(durations), 2) if durations else 0.0

        current_task_title = (
            active_tasks[0]["title"]
            if active_tasks
            else (pending[0]["title"] if pending else "Standing by / Ready for assignment")
        )
        per_employee.append(
            {
                "name": name,
                "role": emp["role"],
                "status": "ACTIVE" if active_tasks else "IDLE",
                "current_task": current_task_title,
                "today_output_count": len(today_done),
                "week_completed_count": len(week_done),
                "tasks_completed": len(completed),
                "tasks_pending": len(pending),
                "tasks_blocked": len(blocked),
                "avg_completion_hours": avg_hrs,
                "kpi_label": emp["kpi_label"],
                "kpi_target": emp["kpi_target"],
            }
        )

    today_tasks = [t for t in tasks if t["timestamp"].startswith(td)]
    leads_today = sum(int(t.get("leads_count") or 0) for t in today_tasks)
    posts_today_tasks = [t for t in today_tasks if int(t.get("posts_count") or 0) > 0 or "post" in t["title"].lower()]
    posts_today_count = sum(max(1, int(t.get("posts_count") or 0)) for t in posts_today_tasks)
    platforms_today = sorted({t["platform"] for t in posts_today_tasks if t.get("platform")})
    top_week = max(per_employee, key=lambda x: x["week_completed_count"]) if per_employee else None

    summary = {
        "total_tasks": len(tasks),
        "running_count": sum(1 for t in tasks if t["status"] == "In Progress"),
        "queued_count": sum(1 for t in tasks if t["status"] == "Queued"),
        "blocked_count": sum(1 for t in tasks if t["status"] == "Blocked"),
        "completed_count": sum(1 for t in tasks if t["status"] == "Completed"),
        "leads_generated_today": leads_today,
        "posts_published_today": posts_today_count,
        "platforms_today": platforms_today,
        "top_employee_this_week": top_week["name"] if top_week else "N/A",
        "top_employee_week_count": top_week["week_completed_count"] if top_week else 0,
    }
    return {"summary": summary, "per_employee": per_employee, "tasks": tasks}


def answer_chat_query(recipient: str, user_message: str) -> str:
    msg = user_message.strip()
    low = msg.lower()
    data = compute_reports_data()
    summary = data["summary"]
    tasks = data["tasks"]
    per_emp = {e["name"].lower(): e for e in data["per_employee"]}

    if any(k in low for k in ["assign a new task", "assign task", "create a task", "new task for"]):
        role_map = {
            "project manager": "Alex", "pm": "Alex", "alex": "Alex",
            "researcher": "Maya", "maya": "Maya",
            "resume": "Liam", "evaluator": "Liam", "liam": "Liam",
            "content writer": "Elena", "writer": "Elena", "elena": "Elena",
            "coordinator": "Noah", "noah": "Noah",
            "auditor": "Zoe", "zoe": "Zoe",
            "support": "Raj", "raj": "Raj",
            "analytics": "Sofia", "sofia": "Sofia",
        }
        target_agent = "Alex" if recipient == "PM" else recipient
        for key, emp_name in role_map.items():
            if key in low:
                target_agent = emp_name
                break

        task_text = msg.split(":", 1)[1].strip() if ":" in msg else msg
        posts_match = re.search(r"(\d+)\s+linkedin\s+posts?", low)
        posts_cnt = int(posts_match.group(1)) if posts_match else (1 if "post" in low else 0)
        platform = "LinkedIn" if "linkedin" in low else "Dashboard"
        deadline = (
            (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            if "tomorrow" in low
            else today_str()
        )
        created = create_task_record(
            title=task_text[:100],
            description=task_text,
            agent_name=target_agent,
            priority="High",
            deadline=deadline,
            assigned_by="Boss (via Chat)",
            status="In Progress",
            platform=platform,
            posts_count=posts_cnt,
        )
        return (
            f"Task created and logged to the ledger: **{created['task_id']}** assigned to "
            f"**{created['agent_name']}** — *\"{created['title']}\"* (Status: `{created['status']}`, "
            f"Deadline: `{created['deadline']}`). {created['sheet_sync']}."
        )

    if recipient != "PM" and recipient.lower() in per_emp:
        emp = per_emp[recipient.lower()]
        emp_tasks = [t for t in tasks if t["agent_name"].lower() == recipient.lower()]
        recent_list = ", ".join(f"{t['task_id']} [{t['status']}]" for t in emp_tasks[:4]) or "none yet"
        return (
            f"**{emp['name']} ({emp['role']})** is currently **{emp['status']}**. "
            f"Current focus: *{emp['current_task']}*. "
            f"Completed today: **{emp['today_output_count']}**, this week: **{emp['week_completed_count']}**, "
            f"pending: **{emp['tasks_pending']}**. Recent tasks: {recent_list}."
        )

    if any(w in low for w in ["running", "currently running", "in progress", "how many projects", "how many tasks"]):
        running = [t for t in tasks if t["status"] == "In Progress"]
        details = ", ".join(f"{t['task_id']} ({t['agent_name']}: {t['title']})" for t in running) or "none"
        return (
            f"There are currently **{summary['running_count']} tasks In Progress** "
            f"(plus {summary['queued_count']} Queued, {summary['blocked_count']} Blocked, "
            f"and {summary['completed_count']} Completed out of {summary['total_tasks']} total tasks). "
            f"Active tasks: {details}."
        )

    if any(w in low for w in ["sales", "leads", "sourcing"]):
        lead_tasks = [t for t in tasks if int(t.get("leads_count") or 0) > 0]
        detail_lines = "; ".join(
            f"{t['task_id']} by {t['agent_name']} ({t['leads_count']} leads, source: {t['platform'] or 'N/A'}, status: {t['status']})"
            for t in lead_tasks
        ) or "No lead-generation tasks logged yet."
        return (
            f"Sourcing/outbound status: **{summary['leads_generated_today']} leads generated today** "
            f"across {len(lead_tasks)} lead task(s). Details: {detail_lines}."
        )

    if any(w in low for w in ["posts", "published", "linkedin", "content"]):
        post_tasks = [t for t in tasks if int(t.get("posts_count") or 0) > 0 or "post" in t["title"].lower()]
        platforms = ", ".join(sorted({t["platform"] for t in post_tasks if t.get("platform")})) or "None"
        items = ", ".join(f"{t['task_id']} ({t['title']} on {t['platform']})" for t in post_tasks) or "none"
        return (
            f"**{summary['posts_published_today']} post(s)** recorded on platform(s): **{platforms}**. "
            f"Entries: {items}."
        )

    if any(w in low for w in ["blocked", "blocker", "stuck", "why"]):
        blocked = [t for t in tasks if t["status"] == "Blocked"]
        if not blocked:
            return "There are currently **0 blocked tasks** in the ledger."
        reasons = "; ".join(
            f"{t['task_id']} ({t['agent_name']} — {t['title']}): {t['blocker_reason'] or 'No reason recorded'}"
            for t in blocked
        )
        return f"**{len(blocked)} task(s) are currently Blocked**: {reasons}."

    if any(w in low for w in ["most tasks", "top employee", "completed the most", "this week"]):
        return (
            f"**{summary['top_employee_this_week']}** completed the most tasks this week with "
            f"**{summary['top_employee_week_count']} completed task(s)**."
        )

    return (
        f"Live Ledger Snapshot: **{summary['completed_count']} Completed**, "
        f"**{summary['running_count']} In Progress**, **{summary['blocked_count']} Blocked**, "
        f"**{summary['queued_count']} Queued**. Top performer this week: "
        f"**{summary['top_employee_this_week']}** ({summary['top_employee_week_count']} done)."
    )


def send_daily_report_email() -> dict:
    data = compute_reports_data()
    s = data["summary"]
    lines = [
        f"TalentFlow Command AI — Daily Executive Report ({today_str()})",
        "=" * 56,
        f"Completed: {s['completed_count']} | In Progress: {s['running_count']} | Blocked: {s['blocked_count']} | Queued: {s['queued_count']}",
        f"Leads Today: {s['leads_generated_today']} | Posts Today: {s['posts_published_today']}",
        "",
        "Employee KPIs:",
    ]
    for emp in data["per_employee"]:
        lines.append(
            f"  - {emp['name']} ({emp['role']}): {emp['status']} | "
            f"Done: {emp['tasks_completed']} | Pending: {emp['tasks_pending']} | "
            f"Today Output: {emp['today_output_count']}"
        )
    body_text = "\n".join(lines)

    smtp_host = get_secret("SMTP_HOST", "").strip()
    smtp_port = int(get_secret("SMTP_PORT", "587"))
    smtp_user = get_secret("SMTP_USER", "").strip()
    smtp_pass = get_secret("SMTP_APP_PASSWORD", "").strip()
    to_email = get_secret("REPORT_TO_EMAIL", "").strip()

    if smtp_host and smtp_user and smtp_pass and to_email:
        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = to_email
            msg["Subject"] = f"[TalentFlow AI] Daily Status Digest — {today_str()}"
            msg.attach(MIMEText(body_text, "plain"))
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            delivery_status = f"Sent via SMTP to {to_email}"
        except Exception as exc:
            delivery_status = f"SMTP error ({exc}); digest logged locally"
    else:
        delivery_status = "Logged locally (add SMTP_USER, SMTP_APP_PASSWORD, REPORT_TO_EMAIL in Streamlit Secrets for live email)"

    conn = get_db()
    sent_at = now_iso()
    conn.execute(
        "INSERT INTO report_logs (sent_at, recipient, delivery_status, summary_text) VALUES (?, ?, ?, ?)",
        (sent_at, to_email or "local-digest", delivery_status, body_text),
    )
    conn.commit()
    conn.close()
    return {"sent_at": sent_at, "delivery_status": delivery_status, "summary_text": body_text}


# ---------------- STREAMLIT UI ----------------
st.set_page_config(page_title="TalentFlow AI — Boss Command Center", page_icon="🎯", layout="wide")
init_db()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🎯 TalentFlow Command AI — Boss Login")
    st.caption("Sign in as the Boss to manage your 7+1 Autonomous AI Agency.")
    with st.form("login_form"):
        u = st.text_input("Boss Username", value="boss")
        p = st.text_input("Boss Password", type="password", placeholder="ChangeMe123!")
        submitted = st.form_submit_button("Enter Command Center", type="primary")
        if submitted:
            if u == BOSS_USERNAME and p == BOSS_PASSWORD:
                st.session_state.authenticated = True
                st.session_state.boss_user = u
                st.rerun()
            else:
                st.error("Invalid Boss credentials.")
    st.stop()

# Header Bar
h1, h2 = st.columns([5, 1])
with h1:
    st.title("🎯 TalentFlow Command AI — Boss Command Center")
    st.caption(f"Signed in as **{st.session_state.get('boss_user', BOSS_USERNAME)}** | 1 Project Manager + 7 Autonomous Specialists")
with h2:
    if st.button("Logout"):
        st.session_state.authenticated = False
        st.rerun()

state = compute_reports_data()
summary = state["summary"]
emp_df = pd.DataFrame(state["per_employee"])
tasks_df = pd.DataFrame(state["tasks"])

# Top Live KPI Row
k1, k2, k3, k4 = st.columns(4)
k1.metric("Running Tasks", summary["running_count"], f"{summary['queued_count']} Queued")
k2.metric("Completed Tasks", summary["completed_count"], f"{summary['total_tasks']} Total")
k3.metric("Blocked Tasks", summary["blocked_count"])
k4.metric("Leads / Posts Today", f"{summary['leads_generated_today']} / {summary['posts_published_today']}")

tab_assign, tab_board, tab_reports, tab_chat, tab_team = st.tabs([
    "A) Task Assignment & Email",
    "B) Live Task Board",
    "C) Reports & KPIs",
    "D) Chat with PM & Team",
    "E) Employee Overview (7+1)",
])

# A) Task Assignment & Email Automation
with tab_assign:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Assign New Task")
        with st.form("assign_task_form", clear_on_submit=True):
            t_title = st.text_input("Task Title", placeholder="e.g., Source 10 Senior Python Engineers in EU")
            agent_labels = [f"{e['name']} — {e['role']}" for e in EMPLOYEES]
            selected_label = st.selectbox("Assign To", agent_labels)
            selected_agent = selected_label.split(" — ")[0]
            c1, c2, c3 = st.columns(3)
            t_priority = c1.selectbox("Priority", VALID_PRIORITIES, index=1)
            t_status = c2.selectbox("Status", VALID_STATUSES, index=1)
            t_deadline = c3.date_input("Deadline", value=datetime.now(timezone.utc).date())
            c4, c5, c6 = st.columns(3)
            t_platform = c4.text_input("Platform / Source", value="Dashboard")
            t_leads = c5.number_input("Leads Count", min_value=0, step=1, value=0)
            t_posts = c6.number_input("Posts Count", min_value=0, step=1, value=0)
            t_desc = st.text_area("Instructions & Expected Output")
            t_blocker = st.text_input("Blocker Reason (if Blocked)")
            if st.form_submit_button("Dispatch Task & Sync Ledger", type="primary"):
                if not t_title.strip():
                    st.error("Task title is required.")
                else:
                    res = create_task_record(
                        title=t_title,
                        description=t_desc,
                        agent_name=selected_agent,
                        priority=t_priority,
                        deadline=str(t_deadline),
                        assigned_by="Boss",
                        status=t_status,
                        platform=t_platform,
                        leads_count=t_leads,
                        posts_count=t_posts,
                        blocker_reason=t_blocker,
                    )
                    st.success(f"Dispatched **{res['task_id']}** to **{res['agent_name']}**. {res['sheet_sync']}")
                    st.rerun()

    with col_b:
        st.subheader("Daily Email Digest Automation")
        st.write("Generates and emails an executive summary of completed, in-progress, blocked tasks, and per-employee KPIs.")
        if st.button("Send / Generate Daily Email Bulletin Now"):
            rep = send_daily_report_email()
            st.info(f"[{rep['sent_at']}] {rep['delivery_status']}")
            st.code(rep["summary_text"])

        conn = get_db()
        logs = [dict(r) for r in conn.execute("SELECT * FROM report_logs ORDER BY id DESC LIMIT 5").fetchall()]
        conn.close()
        if logs:
            st.caption("Recent Report Logs")
            for lg in logs:
                with st.expander(f"{lg['sent_at']} — {lg['delivery_status']}"):
                    st.code(lg["summary_text"])

# B) Live Task Board
with tab_board:
    st.subheader("Live Task Board & Ledger")
    f1, f2, f3, f4 = st.columns(4)
    f_agent = f1.selectbox("Filter by Employee", ["All"] + [e["name"] for e in EMPLOYEES])
    f_status = f2.selectbox("Filter by Status", ["All"] + VALID_STATUSES)
    f_priority = f3.selectbox("Filter by Priority", ["All"] + VALID_PRIORITIES)
    f_date = f4.text_input("Filter by Date (YYYY-MM-DD)", placeholder="e.g., 2026-11-25")

    filtered_df = tasks_df.copy()
    if not filtered_df.empty:
        if f_agent != "All":
            filtered_df = filtered_df[filtered_df["agent_name"] == f_agent]
        if f_status != "All":
            filtered_df = filtered_df[filtered_df["status"] == f_status]
        if f_priority != "All":
            filtered_df = filtered_df[filtered_df["priority"] == f_priority]
        if f_date.strip():
            filtered_df = filtered_df[filtered_df["timestamp"].str.startswith(f_date.strip())]

        display_cols = [
            "task_id", "timestamp", "assigned_by", "agent_name", "title",
            "priority", "status", "deadline", "output_link", "completion_time"
        ]
        st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Inspect & Update Task Status")
        sel_tid = st.selectbox("Select Task ID", filtered_df["task_id"].tolist())
        sel_row = filtered_df[filtered_df["task_id"] == sel_tid].iloc[0].to_dict()
        st.write(f"**Description:** {sel_row['description']}")
        st.write(f"**Platform:** {sel_row.get('platform') or '—'} | **Leads:** {sel_row.get('leads_count', 0)} | **Posts:** {sel_row.get('posts_count', 0)}")
        u1, u2, u3 = st.columns([1, 2, 2])
        new_st = u1.selectbox("New Status", VALID_STATUSES, index=VALID_STATUSES.index(sel_row["status"]))
        new_blk = u2.text_input("Blocker Reason", value=sel_row.get("blocker_reason") or "")
        new_lnk = u3.text_input("Output / Result Link", value=sel_row.get("output_link") or "")
        if st.button("Save Task Update"):
            upd = update_task_status(sel_tid, new_st, new_blk, new_lnk)
            if upd:
                st.success(f"Updated {sel_tid} to {new_st}. {upd['sheet_sync']}")
                st.rerun()

# C) Reports & KPIs
with tab_reports:
    st.subheader("Agency & Per-Employee KPI Report")
    exp1, exp2 = st.columns([1, 3])
    with exp1:
        csv_bytes = tasks_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Ledger CSV",
            data=csv_bytes,
            file_name=f"talentflow_ledger_{today_str()}.csv",
            mime="text/csv",
        )
    with exp2:
        st.caption("Use browser Print (`Ctrl+P` / `Cmd+P`) to export this report view as PDF.")

    st.markdown("#### Employee Output vs Daily KPI Target")
    chart_df = emp_df[["name", "today_output_count", "tasks_completed", "tasks_pending"]].set_index("name")
    st.bar_chart(chart_df)

    st.markdown("#### Per-Employee Performance Table")
    st.dataframe(
        emp_df[["name", "role", "status", "tasks_completed", "tasks_pending", "tasks_blocked", "avg_completion_hours", "today_output_count"]],
        use_container_width=True,
        hide_index=True,
    )

# D) Chat with PM & Employees
with tab_chat:
    st.subheader("Direct Chat with Project Manager & Team (Real Ledger Data)")
    chat_options = ["PM"] + [e["name"] for e in EMPLOYEES]
    thread_key = st.selectbox(
        "Chat Recipient",
        chat_options,
        format_func=lambda x: "Alex — Project Manager (Chief of Staff)" if x == "PM" else x,
    )

    st.caption(
        "Try asking: *'How many projects/tasks are currently running?'*, "
        "*'What is the status of the sales team? How many leads were generated today?'*, "
        "*'How many posts were published today, and on which platforms?'*, "
        "*'Which tasks are blocked, and why?'*, "
        "*'Which employee completed the most tasks this week?'*, or "
        "*'Assign a new task to the Content Writer: write 3 LinkedIn posts about our new service, due tomorrow.'*"
    )

    conn = get_db()
    msgs = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM chat_messages WHERE thread_key = ? ORDER BY id ASC",
            (thread_key,),
        ).fetchall()
    ]
    conn.close()

    for m in msgs:
        role_avatar = "user" if m["sender"] == "Boss" else "assistant"
        with st.chat_message(role_avatar):
            st.markdown(f"**{m['sender']}** *({m['created_at']})*\n\n{m['message']}")

    prompt = st.chat_input(f"Message {thread_key}...")
    if prompt:
        ts = now_iso()
        conn = get_db()
        conn.execute(
            "INSERT INTO chat_messages (thread_key, sender, recipient, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_key, "Boss", thread_key, prompt, ts),
        )
        reply = answer_chat_query(thread_key, prompt)
        conn.execute(
            "INSERT INTO chat_messages (thread_key, sender, recipient, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_key, thread_key, "Boss", reply, now_iso()),
        )
        conn.commit()
        conn.close()
        st.rerun()

# E) Employee Overview (7+1)
with tab_team:
    st.subheader("7+1 Autonomous AI Employee Roster")
    cols = st.columns(4)
    for idx, emp in enumerate(state["per_employee"]):
        with cols[idx % 4]:
            with st.container(border=True):
                badge = "🟢 ACTIVE" if emp["status"] == "ACTIVE" else "🟡 IDLE"
                st.markdown(f"### {emp['name']}")
                st.caption(emp["role"])
                st.markdown(f"**Status:** {badge}")
                st.markdown(f"**Current Task:** {emp['current_task']}")
                st.metric("Today's Output", emp["today_output_count"], f"Target: {emp['kpi_target']}")
