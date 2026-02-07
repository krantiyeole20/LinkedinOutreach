import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

# Use the same path as settings.py
CREDENTIALS_FILE = Path("/Users/krantiy/Documents/Linkedin Automation Project/config/credentials.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def list_sheets():
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        print(f"Service Account Email: {creds.service_account_email}")
        print("\nListing accessible spreadsheets:")
        print("="*60)
        
        sheets = client.openall()
        if not sheets:
            print("No spreadsheets found! Please share standard sheets with the service account email above.")
        
        for sheet in sheets:
            print(f"Title: '{sheet.title}' | ID: {sheet.id}")
            
        print("="*60)
        
        # Verify specific expected names
        expected = ["LinkedIn_Profiles_Input", "LinkedIn_Engagement_Log", "LinkedIn_State_Tracker"]
        found_titles = [s.title for s in sheets]
        
        print("\nChecking required sheets:")
        for name in expected:
            status = "✅ Found" if name in found_titles else "❌ MISSING"
            print(f"{status}: {name}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_sheets()
