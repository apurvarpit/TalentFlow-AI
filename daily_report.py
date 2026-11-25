from dotenv import load_dotenv
from app import init_db, send_daily_report_email

load_dotenv()

if __name__ == "__main__":
    init_db()
    res = send_daily_report_email()
    print(f"[{res['sent_at']}] {res['delivery_status']}")
    print(res["summary_text"])
