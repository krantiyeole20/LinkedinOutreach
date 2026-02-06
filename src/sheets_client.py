import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import List, Optional
import random

import structlog

from config.settings import settings

logger = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class SheetsClient:
    def __init__(self):
        self.credentials = Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE,
            scopes=SCOPES
        )
        self.client = gspread.authorize(self.credentials)
        
        self.input_sheet = None
        self.log_sheet = None
        self.state_sheet = None
    
    def connect(self):
        try:
            input_wb = self.client.open(settings.INPUT_SHEET_NAME)
            self.input_sheet = input_wb.sheet1
            
            log_wb = self.client.open(settings.LOG_SHEET_NAME)
            self.log_sheet = log_wb.sheet1
            
            state_wb = self.client.open(settings.STATE_TRACKER_SHEET_NAME)
            self.state_sheet = state_wb.sheet1
            
            logger.info("sheets_connected")
        except Exception as e:
            logger.error("sheets_connection_failed", error=str(e))
            raise
    
    def get_all_profiles(self) -> List[dict]:
        records = self.input_sheet.get_all_records()
        return [
            {"name": r.get("name"), "linkedin_url": r.get("linkedin_url")}
            for r in records
            if r.get("linkedin_url")
        ]
    
    def get_state_tracker_data(self) -> List[dict]:
        records = self.state_sheet.get_all_records()
        return records
    
    def initialize_state_tracker(self):
        """First run: populate state tracker from input sheet"""
        profiles = self.get_all_profiles()
        existing = {r["linkedin_url"] for r in self.get_state_tracker_data()}
        
        new_rows = []
        for profile in profiles:
            if profile["linkedin_url"] not in existing:
                new_rows.append([
                    profile["linkedin_url"],
                    "",
                    0,
                    0,
                    0,
                    "active",
                    ""
                ])
        
        if new_rows:
            self.state_sheet.append_rows(new_rows)
            logger.info("state_tracker_initialized", new_profiles=len(new_rows))
    
    def update_profile_state(
        self,
        linkedin_url: str,
        last_engaged_date: Optional[datetime] = None,
        increment_engagement: bool = False,
        increment_skip: bool = False,
        reset_skips: bool = False,
        status: Optional[str] = None,
        last_post_date: Optional[datetime] = None
    ):
        try:
            cell = self.state_sheet.find(linkedin_url)
            if not cell:
                logger.warning("profile_not_found_in_tracker", url=linkedin_url)
                return
            
            row = cell.row
            
            if last_engaged_date:
                self.state_sheet.update_cell(row, 2, last_engaged_date.isoformat())
            
            if increment_engagement:
                current = int(self.state_sheet.cell(row, 3).value or 0)
                self.state_sheet.update_cell(row, 3, current + 1)
            
            if increment_skip:
                current = int(self.state_sheet.cell(row, 4).value or 0)
                self.state_sheet.update_cell(row, 4, current + 1)
            
            if reset_skips:
                self.state_sheet.update_cell(row, 4, 0)
            
            if status:
                self.state_sheet.update_cell(row, 6, status)
            
            if last_post_date:
                self.state_sheet.update_cell(row, 7, last_post_date.isoformat())
                
        except Exception as e:
            logger.error("update_state_failed", url=linkedin_url, error=str(e))
    
    def log_engagement(
        self,
        name: str,
        linkedin_url: str,
        action_type: str,
        post_id: str,
        post_content: str,
        status: str,
        error_message: str = ""
    ):
        now = datetime.now()
        row = [
            now.isoformat(),
            name,
            linkedin_url,
            action_type,
            post_id,
            post_content[:200] if post_content else "",
            status,
            error_message,
            now.isocalendar()[1],
            now.strftime("%A")
        ]
        
        try:
            self.log_sheet.append_row(row)
            logger.info("engagement_logged", url=linkedin_url, status=status)
        except Exception as e:
            logger.error("log_engagement_failed", error=str(e))


_client_instance = None

def get_sheets_client() -> SheetsClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = SheetsClient()
        _client_instance.connect()
    return _client_instance


def generate_daily_queue():
    from src.scheduler import Scheduler

    client = get_sheets_client()
    client.initialize_state_tracker()
    scheduler = Scheduler()
    queue = scheduler.get_todays_queue()
    if not queue:
        return []

    print("\n" + "=" * 50)
    print("TODAY'S ENGAGEMENT QUEUE")
    print("=" * 50)
    for i, engagement in enumerate(queue, 1):
        print(f"{i:2}. {engagement.name[:30]:30} | Score: {engagement.priority_score:.1f} @ {engagement.scheduled_time.strftime('%H:%M')}")
    print("=" * 50 + "\n")
    return queue


def show_queue():
    queue = generate_daily_queue()
    return queue


def test_connection():
    try:
        client = get_sheets_client()
        profiles = client.get_all_profiles()
        print(f"Connected successfully - Found {len(profiles)} profiles")
    except Exception as e:
        print(f"Connection failed: {e}")
