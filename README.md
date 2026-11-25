# TalentFlow Command AI — Autonomous 7+1 AI Agency

An autonomous recruitment & technical talent operations agency powered by **8 AI Employees (1 Project Manager + 7 Specialists)** and a live **Boss Command Center Dashboard** built with Streamlit.

## Features
- **Boss Login Gate:** Credential-protected access (`BOSS_USERNAME` / `BOSS_PASSWORD`).
- **A) Task Assignment & Daily Email:** Assign tasks to the Project Manager (`Alex`) or any of the 7 specialists with automatic ledger logging, plus one-click or scheduled daily email reports.
- **B) Live Task Board:** Filter tasks by employee, status (`Queued`, `In Progress`, `Blocked`, `Completed`), priority, and date; inspect details and update status live.
- **C) Reports & KPIs:** Per-employee performance metrics, daily/weekly summary KPIs, visual bar charts, CSV export, and printable PDF view.
- **D) Chat with PM & Employees:** Natural-language chat backed by **live database/ledger state**, saved chat history, and direct task creation from chat.
- **E) Employee Overview:** Live status cards (`ACTIVE` / `IDLE`), current task, and daily output count for all 8 AI employees.

## Local Setup
```bash
git clone <your-repo-url>
cd TalentFlow-AI
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

## Test Login Credentials
- **Username:** `boss`
- **Password:** `ChangeMe123!`

## Deploy on Streamlit Community Cloud
1. Upload all files in this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
3. Click **Create app**, choose your repo, branch `main`, and main file `app.py`.
4. Paste your secrets from `.env.example` under **Advanced settings -> Secrets** and click **Deploy**.
