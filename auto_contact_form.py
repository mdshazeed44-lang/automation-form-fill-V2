"""
FORM AUTO-FILLER - ASYNC VERSION WITH STATUS UPDATES
====================================================
Parallel form automation with Google Sheets status updates

Author: AI Development Team
Version: 4.1.0 - FIXED EDITION
Date: 2025-01-30
"""

import pandas as pd
from playwright.async_api import async_playwright
import asyncio
import time
from datetime import datetime
import json
import os
from typing import Dict, List, Tuple, Optional
import traceback
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# =========================
# CONFIGURATION MANAGEMENT
# =========================

class Config:
    """Centralized configuration management"""
    # Google Sheets Configuration
    GOOGLE_SHEETS_ID = "1ZuplfaKjpco06iYjlF_MgeDZkoOTaVrymP-4O4jZpPE"
    WEBSITE_SHEET_RANGE = "'Database'!A:A"
    DETAILS_SHEET_RANGE = "'Details to fill'!A:E"
    STATUS_COLUMN_RANGE = "'Database'!B:B"
   
    GOOGLE_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # Parallel Processing
    MAX_PARALLEL_WORKERS = 1  # Start with 1 for testing

    # Default Field Values
    DEFAULT_VALUES = {
        "name": "Interested Customer",
        "email": "contact.inquiry@example.com",
        "phone": "9876543210",
        "message": "Hello, I am interested in your services and would like to discuss further. Please contact me.",
        "country": "India",
    }

    # Smart Default Mappings
    SMART_DEFAULTS = {
        "job": "Business Owner",
        "company": "Private Business",
        "position": "Manager",
        "designation": "Director",
        "organization": "Self Employed",
        "profession": "Entrepreneur",
        "occupation": "Business",
        "country": "India",
        "city": "Delhi",
        "state": "Delhi",
        "address": "Delhi, India",
        "gender": "Male",
        "age": "30",
        "subject": "General Inquiry",
        "topic": "Business Inquiry",
        "department": "Sales",
        "website": "www.example.com",
        "title": "Mr",
    }

    # CAPTCHA Settings
    CAPTCHA_WAIT_TIME = 15
    CAPTCHA_CHECK_INTERVAL = 0.2
    CAPTCHA_RECHECK_ATTEMPTS = 5
    AUTO_CLICK_CAPTCHA = True

    # Performance Settings
    ANIMATION_DELAY = 0.1
    PAGE_LOAD_TIMEOUT = 30000
    ELEMENT_TIMEOUT = 2000
    FIELD_FILL_DELAY = 50

    # Retry Settings
    MAX_RETRIES = 2
    RETRY_DELAY = 2

    # Browser Settings
    HEADLESS = True  # False to see browser
    SLOW_MO = 100


# =========================
# GOOGLE SHEETS API CLIENT
# =========================

class GoogleSheetsClient:
    """Handle Google Sheets API with READ + WRITE capabilities"""

    def __init__(self, credentials_env_var: str = Config.GOOGLE_CREDENTIALS_ENV, credentials_file: Optional[str] = None):
        self.credentials_env_var = credentials_env_var
        self.credentials_file = credentials_file
        self.service = None
        self.creds_dict = None
        self.authenticate()

    def authenticate(self):
        """Authenticate with Google Sheets API"""
        try:
            print("🔐 Authenticating with Google Sheets API...")

            creds_json = os.getenv(self.credentials_env_var)

            if creds_json:
                try:
                    self.creds_dict = json.loads(creds_json)
                except Exception as e:
                    raise RuntimeError(f"Invalid JSON in environment variable: {e}")
                creds = Credentials.from_service_account_info(self.creds_dict, scopes=Config.SCOPES)

            elif self.credentials_file and os.path.exists(self.credentials_file):
                with open(self.credentials_file, "r") as f:
                    self.creds_dict = json.load(f)
                creds = Credentials.from_service_account_info(self.creds_dict, scopes=Config.SCOPES)

            else:
                raise FileNotFoundError(
                    f"Google credentials not found. Set {self.credentials_env_var} or provide credentials_file"
                )

            self.service = build('sheets', 'v4', credentials=creds)
            print("✅ Successfully authenticated with Google Sheets API")

        except Exception as e:
            print(f"❌ Authentication failed: {str(e)}")
            raise

    def update_status(self, spreadsheet_id: str, row_number: int, status: str):
        """Update status in Google Sheet"""
        try:
            sheet_row = row_number + 2
            range_name = f"Database!B{sheet_row}"
            body = {'values': [[status]]}
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            print(f"   📊 Status updated: {status}")
        except Exception as e:
            print(f"   ⚠️ Failed to update status: {str(e)}")

    def read_two_sheets(self, spreadsheet_id: str, websites_range: str, details_range: str) -> pd.DataFrame:
        """Read from two sheets and combine data"""
        try:
            print("\n📋 Reading Website URLs...")
            websites_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=websites_range
            ).execute()

            websites_values = websites_result.get('values', [])
            if not websites_values or len(websites_values) <= 1:
                print("❌ No website URLs found")
                return pd.DataFrame()

            websites = [row[0] for row in websites_values[1:] if row and len(row) > 0]
            print(f"✅ Found {len(websites)} websites")

            print("\n📋 Reading Form Details...")
            details_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=details_range
            ).execute()

            details_values = details_result.get('values', [])
            if not details_values or len(details_values) <= 1:
                print("❌ No form details found")
                return pd.DataFrame()

            details_df = pd.DataFrame(details_values[1:], columns=details_values[0])
            form_data = details_df.iloc[0].to_dict()

            combined_data = []
            for idx, website in enumerate(websites):
                row_data = {'website': website, 'row_index': idx}
                row_data.update(form_data)
                combined_data.append(row_data)

            return pd.DataFrame(combined_data)

        except Exception as e:
            print(f"❌ Error reading sheets: {str(e)}")
            raise


# =========================
# ASYNC CAPTCHA HANDLER
# =========================

class AsyncCaptchaHandler:
    """Async CAPTCHA detection and handling"""

    CAPTCHA_SELECTORS = [
        "iframe[src*='recaptcha']",
        "iframe[src*='google.com/recaptcha']",
        "div.g-recaptcha",
        ".g-recaptcha",
        "iframe[src*='hcaptcha']",
        "div.h-captcha",
        ".h-captcha",
    ]

    @staticmethod
    async def detect(page) -> Tuple[bool, str]:
        """Detect if CAPTCHA is present"""
        for selector in AsyncCaptchaHandler.CAPTCHA_SELECTORS:
            try:
                elements = page.locator(selector)
                if await elements.count() > 0:
                    elem = elements.first
                    if await elem.is_visible(timeout=500):
                        return True, selector
            except:
                continue
        return False, ""

    @staticmethod
    async def wait_for_solve(page, timeout: int = Config.CAPTCHA_WAIT_TIME) -> bool:
        """Wait for CAPTCHA solve"""
        print(f"\n   🤖 CAPTCHA DETECTED - Waiting {timeout}s for manual solve...")
        
        start = time.time()
        while (time.time() - start) < timeout:
            has_captcha, _ = await AsyncCaptchaHandler.detect(page)
            if not has_captcha:
                print("   ✅ CAPTCHA SOLVED!")
                await asyncio.sleep(1)
                return True
            await asyncio.sleep(Config.CAPTCHA_CHECK_INTERVAL)

        print("   ⏱️ CAPTCHA timeout")
        return False


# =========================
# ASYNC FIELD FILLER
# =========================

class AsyncFieldFiller:
    """Async field filling operations"""

    @staticmethod
    async def fill_text(element, value: str) -> bool:
        """Fill text input or textarea"""
        try:
            if not await element.is_visible(timeout=1000):
                return False

            await element.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.1)

            await element.click(timeout=2000)
            await asyncio.sleep(0.1)

            await element.fill("")
            await asyncio.sleep(0.05)

            await element.type(str(value), delay=Config.FIELD_FILL_DELAY)
            await asyncio.sleep(0.1)

            await element.evaluate("el => el.dispatchEvent(new Event('change', {bubbles: true}))")
            
            return True

        except Exception as e:
            print(f"      ⚠️ Fill error: {str(e)[:50]}")
            return False

    @staticmethod
    async def fill_dropdown(element, value: str) -> bool:
        """Fill dropdown"""
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.1)

            options = await element.evaluate("""
                el => Array.from(el.options).map(opt => ({
                    text: opt.text.trim(),
                    value: opt.value
                }))
            """)

            if not options:
                return False

            value_lower = str(value).lower()

            # Try exact match
            for opt in options:
                if opt['text'].lower() == value_lower:
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    return True

            # Try contains match
            for opt in options:
                if value_lower in opt['text'].lower():
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    return True

            # Select first non-placeholder
            placeholders = ['select', 'choose', '--', 'please']
            for opt in options:
                if opt['text'] and not any(p in opt['text'].lower() for p in placeholders):
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    return True

            return False

        except Exception as e:
            print(f"      ⚠️ Dropdown error: {str(e)[:50]}")
            return False


# =========================
# ASYNC FORM PROCESSOR
# =========================

class AsyncFormProcessor:
    """Async form processing"""

    def __init__(self, page, row, website: str, sheets_client: GoogleSheetsClient, row_index: int):
        self.page = page
        self.row = row
        self.website = website
        self.sheets_client = sheets_client
        self.row_index = row_index
        self.filled_count = 0
        self.total_fields = 0

    def get_value(self, field_name: str) -> str:
        """Get value for field"""
        field_mapping = {
            'name': 'Name',
            'email': 'Email',
            'phone': 'Phone',
            'message': 'Message',
            'country': 'Country',
        }

        sheet_column = field_mapping.get(field_name.lower(), field_name)
        value = self.row.get(sheet_column, "")

        if pd.isna(value) or not str(value).strip():
            value = self.row.get(field_name, "")

        if not pd.isna(value) and str(value).strip():
            return str(value).strip()

        if field_name in Config.DEFAULT_VALUES:
            return Config.DEFAULT_VALUES[field_name]

        field_lower = field_name.lower()
        for key, default_val in Config.SMART_DEFAULTS.items():
            if key in field_lower or field_lower in key:
                return default_val

        return "N/A"

    async def process_all_fields(self) -> int:
        """Process all form fields - IMPROVED VERSION"""
        try:
            print(f"   ⏳ Waiting for page to stabilize...")
            await asyncio.sleep(3)
            
            # Take screenshot
            try:
                screenshot_path = f"debug_site_{self.row_index}.png"
                await self.page.screenshot(path=screenshot_path, full_page=True)
                print(f"   📸 Screenshot: {screenshot_path}")
            except:
                pass
            
            # Count fields
            all_inputs = await self.page.locator("input").count()
            visible_inputs = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image'])").count()
            textarea_count = await self.page.locator("textarea:visible").count()
            select_count = await self.page.locator("select:visible").count()
            
            print(f"   🔍 FIELD DETECTION:")
            print(f"      Total inputs: {all_inputs}")
            print(f"      Fillable inputs: {visible_inputs}")
            print(f"      Textareas: {textarea_count}")
            print(f"      Dropdowns: {select_count}")
            
            self.total_fields = visible_inputs + textarea_count + select_count

            if self.total_fields == 0:
                print(f"   ❌ NO FILLABLE FIELDS FOUND")
                
                # Check for iframes
                iframe_count = await self.page.locator("iframe").count()
                if iframe_count > 0:
                    print(f"   🖼️ Found {iframe_count} iframes (form might be inside)")
                
                # Current page info
                print(f"   📍 URL: {self.page.url}")
                print(f"   📄 Title: {await self.page.title()}")
                
                return 0

            print(f"   ✅ Starting to fill {self.total_fields} fields...\n")

            # Fill inputs
            all_inputs_list = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image'])").all()
            
            for idx, inp in enumerate(all_inputs_list):
                try:
                    field_type = await self.detect_field_type(inp)
                    value = self.get_value(field_type)
                    
                    print(f"      [{idx+1}/{len(all_inputs_list)}] Filling '{field_type}': {value[:30]}...")
                    
                    if await AsyncFieldFiller.fill_text(inp, value):
                        self.filled_count += 1
                        print(f"      ✅ Success")
                    else:
                        print(f"      ⚠️ Failed")
                        
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                    
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill textareas
            all_textareas = await self.page.locator("textarea:visible").all()
            for idx, ta in enumerate(all_textareas):
                try:
                    value = self.get_value('message')
                    print(f"      Filling textarea {idx+1}: {value[:30]}...")
                    
                    if await AsyncFieldFiller.fill_text(ta, value):
                        self.filled_count += 1
                        print(f"      ✅ Textarea filled")
                        
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill selects
            all_selects = await self.page.locator("select:visible").all()
            for idx, sel in enumerate(all_selects):
                try:
                    field_type = await self.detect_field_type(sel)
                    value = self.get_value(field_type)
                    print(f"      Filling dropdown {idx+1}: {field_type}...")
                    
                    if await AsyncFieldFiller.fill_dropdown(sel, value):
                        self.filled_count += 1
                        print(f"      ✅ Dropdown filled")
                        
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

        except Exception as e:
            print(f"   ❌ Field processing error: {str(e)}")
            traceback.print_exc()

        return self.filled_count

    async def detect_field_type(self, element) -> str:
        """Detect field type"""
        try:
            info = await element.evaluate("""
                el => {
                    const labels = el.labels || [];
                    const label = labels[0]?.textContent || '';
                    return {
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        type: el.type || '',
                        label: label
                    };
                }
            """)
            
            combined = ' '.join([
                info.get('name', ''),
                info.get('id', ''),
                info.get('placeholder', ''),
                info.get('label', '')
            ]).lower()

            if 'email' in combined or info.get('type') == 'email':
                return 'email'
            if 'phone' in combined or 'tel' in combined or info.get('type') == 'tel':
                return 'phone'
            if 'name' in combined and 'email' not in combined:
                return 'name'
            if 'message' in combined or 'comment' in combined or 'query' in combined:
                return 'message'
            if 'country' in combined:
                return 'country'

            return info.get('name') or info.get('id') or 'unknown'

        except:
            return 'unknown'


# =========================
# ASYNC WORKER
# =========================

async def process_website_async(row, idx: int, total: int, sheets_client: GoogleSheetsClient, playwright_instance):
    """Async worker to process single website"""
    website = str(row.get("website","")).strip()
    row_index = int(row.get('row_index', idx))

    print(f"\n{'='*90}")
    print(f"🌐 [{idx+1}/{total}] {website}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*90}\n")

    # Update status: PROCESSING
    try:
        sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "PROCESSING")
    except Exception as e:
        print(f"   ⚠️ Status update failed: {e}")

    browser = None
    try:
        # Launch browser
        browser = await playwright_instance.chromium.launch(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        page = await context.new_page()

        # Navigate
        try:
            print(f"   🔄 Loading website...")
            await page.goto(website, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
            await asyncio.sleep(2)
            print(f"   ✅ Website loaded: {page.url}")
        except Exception as nav_err:
            print(f"   ❌ Navigation error: {nav_err}")
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NAV_ERROR")
            return False

        # Check CAPTCHA
        has_captcha, _ = await AsyncCaptchaHandler.detect(page)
        if has_captcha:
            print(f"   🤖 CAPTCHA detected")
            if not await AsyncCaptchaHandler.wait_for_solve(page):
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "CAPTCHA_BLOCKED")
                return False

        # Find contact link - IMPROVED
        try:
            contact_found = False
            keywords = [
                "Contact Us", "Contact", "Get in Touch",
                "Contact Form", "Enquiry", "Inquiry",
                "Get Started", "Book", "Appointment"
            ]
            
            print(f"   🔎 Searching for contact page...")
            
            for keyword in keywords:
                try:
                    # Try text-based search first (more reliable)
                    links = page.locator(f"a:has-text('{keyword}')")
                    count = await links.count()
                    
                    if count > 0:
                        first_link = links.first
                        if await first_link.is_visible(timeout=1000):
                            href = await first_link.get_attribute('href')
                            print(f"   ✅ Found '{keyword}' link: {href}")
                            
                            await first_link.click(timeout=5000)
                            contact_found = True
                            break
                except Exception as e:
                    print(f"   ⚠️ '{keyword}' search failed: {str(e)[:50]}")
                    continue

            if contact_found:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                    print(f"   ✅ Contact page opened: {page.url}")
                except:
                    pass
            else:
                print(f"   ⚠️ No contact link found - will try current page")
                
        except Exception as e:
            print(f"   ⚠️ Contact search error: {str(e)[:100]}")

        # Extra wait for dynamic content
        await asyncio.sleep(2)

        # Process form
        processor = AsyncFormProcessor(page, row, website, sheets_client, row_index)
        filled = await processor.process_all_fields()

        if filled > 0:
            print(f"\n   ✅ Filled {filled}/{processor.total_fields} fields")

            # Submit
            try:
                print(f"   🔍 Looking for submit button...")
                
                # Try multiple submit selectors
                submit_selectors = [
                    "button[type='submit']:visible",
                    "input[type='submit']:visible",
                    "button:has-text('Submit'):visible",
                    "button:has-text('Send'):visible",
                    "input[value='Submit']:visible",
                    "input[value='Send']:visible"
                ]
                
                submit_found = False
                for selector in submit_selectors:
                    try:
                        btns = page.locator(selector)
                        if await btns.count() > 0:
                            btn = btns.first
                            if await btn.is_visible(timeout=1000):
                                print(f"   🎯 Found submit button: {selector}")
                                await btn.click(timeout=5000)
                                print(f"   ✅ Form submitted!")
                                submit_found = True
                                break
                    except:
                        continue
                
                if submit_found:
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "SUCCESS")
                    await asyncio.sleep(2)
                else:
                    print(f"   ⚠️ Submit button not found")
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FILLED_NO_SUBMIT")
                    
                return True
                
            except Exception as submit_err:
                print(f"   ⚠️ Submit error: {submit_err}")
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FILLED_SUBMIT_ERROR")
                return True
        else:
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NO_FIELDS")
            return False

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        traceback.print_exc()
        sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FAILED")
        return False

    finally:
        if browser:
            try:
                await browser.close()
            except:
                pass


# =========================
# MAIN ASYNC EXECUTOR
# =========================

async def main_async():
    """Main async execution"""
    print("="*90)
    print("🚀 FORM AUTO-FILLER - v4.1 FIXED EDITION")
    print(f"   ⚡ Max Parallel Workers: {Config.MAX_PARALLEL_WORKERS}")
    print(f"   👁️ Headless Mode: {Config.HEADLESS}")
    print("="*90)
    print()

    # Setup Google Sheets
    sheets_client = GoogleSheetsClient(credentials_file="form-automation-484413-489b8d00026a.json")

    # Load data
    df = sheets_client.read_two_sheets(
        Config.GOOGLE_SHEETS_ID,
        Config.WEBSITE_SHEET_RANGE,
        Config.DETAILS_SHEET_RANGE
    )

    if df.empty:
        print("❌ No data found")
        return

    print(f"\n✅ Loaded {len(df)} websites\n")

    # Initialize Playwright
    playwright_instance = await async_playwright().start()

    # Process websites
    for idx, row in df.iterrows():
        await process_website_async(row, idx, len(df), sheets_client, playwright_instance)
        
        # Small delay between websites
        if idx < len(df) - 1:
            print("\n⏸️ Waiting before next website...\n")
            await asyncio.sleep(3)

    await playwright_instance.stop()

    print("\n" + "="*90)
    print("✅ ALL PROCESSING COMPLETE")
    print("="*90)


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    import sys
    
    try:
        print(f"🚀 Starting at {datetime.now()}")
        print(f"📍 Running in: {os.getenv('HOSTNAME', 'local')}")
        print(f"🔢 Process ID: {os.getpid()}\n")
        
        asyncio.run(main_async())
        
        print(f"\n✅ Completed at {datetime.now()}")
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Execution interrupted by user")
        sys.exit(1)
        
    except Exception as e:
        print(f"\n\n❌ Fatal error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)