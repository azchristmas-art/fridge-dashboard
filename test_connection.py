import os
import gspread
from dotenv import load_dotenv

# 1. LOAD CONFIGURATION
# Read settings from our private .env file
load_dotenv()

# Grab the unique Google Sheet identifier
sheet_id = os.getenv("GOOGLE_SHEET_ID")
credentials_file = "credentials.json"

print("\n--- Starting Google Sheets Handshake Test ---")

# Guard check: ensure credentials.json is actually sitting in the folder
if not os.path.exists(credentials_file):
    print("❌ ERROR: Could not find 'credentials.json' in this folder.")
    print("Please ensure your Google robot key is saved as credentials.json here.")
    exit(1)

# Guard check: ensure GOOGLE_SHEET_ID is present in .env
if not sheet_id:
    print("❌ ERROR: 'GOOGLE_SHEET_ID' is missing from your .env file.")
    print("Please add GOOGLE_SHEET_ID=your_id to .env and try again.")
    exit(1)

try:
    print("🔑 Authenticating with Google Cloud using credentials.json...")
    # Log in as our robot service account
    client = gspread.service_account(filename=credentials_file)

    print(f"📄 Attempting to open spreadsheet ID: {sheet_id[:8]}...")
    # Open the spreadsheet by its unique key
    spreadsheet = client.open_by_key(sheet_id)

    print("\n✅ HANDSHAKE SUCCESSFUL!")
    print(f"Spreadsheet Title: '{spreadsheet.title}'")
    
    # List the tabs inside to prove two-way reading works
    sheet_names = [ws.title for ws in spreadsheet.worksheets()]
    print(f"Available Tabs: {sheet_names}\n")

except gspread.exceptions.SpreadsheetNotFound:
    print("\n❌ SPREADSHEET NOT FOUND:")
    print("Python reached Google, but Google could not find that Sheet ID.")
    print("Double check that the ID in your .env file matches the browser URL exactly.")

except Exception as err:
    print(f"\n❌ CONNECTION FAILED: {err}")
    print("\nTip: If you see a 'Permission denied' (403) error, verify that")
    print("fridge-bot@boulevard-system.iam.gserviceaccount.com")
    print("has been added as an 'Editor' in your Google Sheet's Share menu.")

