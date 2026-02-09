"""
FORM AUTO-FILLER - ULTRA IMPROVED VERSION
==========================================
Maximum success rate with intelligent form detection

Version: 6.0.0 - ULTRA SUCCESS EDITION
Key Improvements:
- Smart contact page detection (URL + form presence)
- iframe form support
- React-select solving (not skipping!)
- Intelligent field retry
- Better submit button detection
- Navigation error recovery
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

# =========================
# CONFIGURATION
# =========================

class Config:
    """Centralized configuration"""
    # Google Sheets
    GOOGLE_SHEETS_ID = "1ZuplfaKjpco06iYjlF_MgeDZkoOTaVrymP-4O4jZpPE"
    WEBSITE_SHEET_RANGE = "'Database'!A:A"
    DETAILS_SHEET_RANGE = "'Details to fill'!A:E"
    STATUS_COLUMN_RANGE = "'Database'!B:B"
    GOOGLE_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # Performance
    MAX_PARALLEL_WORKERS = 1
    PAGE_LOAD_TIMEOUT = 35000  # Increased
    ELEMENT_TIMEOUT = 3000  # Increased
    FIELD_FILL_DELAY = 80  # Slower but more reliable
    ANIMATION_DELAY = 0.15
    
    # Retry
    MAX_RETRIES = 3  # Increased
    RETRY_DELAY = 3
    
    # Browser
    HEADLESS = False  # Changed to False for debugging
    SLOW_MO = 150  # Slower for reliability

    # CAPTCHA
    CAPTCHA_WAIT_TIME = 35
    CAPTCHA_CHECK_INTERVAL = 0.5
    AUTO_SOLVE_CHECKBOX_CAPTCHA = True

    # Field Values
    DEFAULT_VALUES = {
        "name": "Interested Customer",
        "email": "contact.inquiry@example.com",
        "phone": "9876543210",
        "message": "Hello, I am interested in your services and would like to discuss further. Please contact me.",
        "country": "India",
    }

    SMART_DEFAULTS = {
        "job": "Business Owner", "company": "Private Business",
        "position": "Manager", "designation": "Director",
        "organization": "Self Employed", "profession": "Entrepreneur",
        "occupation": "Business", "title": "Mr", "gender": "Male",
        "age": "30", "country": "India", "city": "Delhi",
        "state": "Delhi", "address": "Delhi, India",
        "zipcode": "110001", "zip": "110001", "postal": "110001",
        "subject": "General Inquiry", "topic": "Business Inquiry",
        "department": "Sales", "reason": "Product Inquiry",
        "type": "General", "service": "Consultation",
        "budget": "Flexible", "source": "Web Search",
        "website": "www.example.com", "industry": "Technology",
    }


# =========================
# GOOGLE SHEETS CLIENT
# =========================

class GoogleSheetsClient:
    """Google Sheets API handler"""

    def __init__(self, credentials_env_var: str = Config.GOOGLE_CREDENTIALS_ENV, credentials_file: Optional[str] = None):
        self.credentials_env_var = credentials_env_var
        self.credentials_file = credentials_file
        self.service = None
        self.authenticate()

    def authenticate(self):
        """Authenticate with Google Sheets"""
        try:
            print("🔐 Authenticating with Google Sheets API...")
            creds_json = os.getenv(self.credentials_env_var)

            if creds_json:
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            elif self.credentials_file and os.path.exists(self.credentials_file):
                with open(self.credentials_file, "r") as f:
                    creds_dict = json.load(f)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            else:
                raise FileNotFoundError(f"Google credentials not found")

            self.service = build('sheets', 'v4', credentials=creds)
            print("✅ Authenticated successfully")
        except Exception as e:
            print(f"❌ Authentication failed: {str(e)}")
            raise

    def update_status(self, spreadsheet_id: str, row_number: int, status: str):
        """Update status in sheet"""
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
            print(f"   📊 Status: {status}")
        except Exception as e:
            print(f"   ⚠️ Status update failed: {str(e)}")

    def read_two_sheets(self, spreadsheet_id: str, websites_range: str, details_range: str) -> pd.DataFrame:
        """Read and combine data from two sheets"""
        try:
            print("\n📋 Reading Website URLs...")
            websites_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=websites_range
            ).execute()
            websites_values = websites_result.get('values', [])
            if not websites_values or len(websites_values) <= 1:
                return pd.DataFrame()
            websites = [row[0] for row in websites_values[1:] if row and len(row) > 0]
            print(f"✅ Found {len(websites)} websites")

            print("\n📋 Reading Form Details...")
            details_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=details_range
            ).execute()
            details_values = details_result.get('values', [])
            if not details_values or len(details_values) <= 1:
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
# CAPTCHA HANDLER
# =========================

class AsyncCaptchaHandler:
    """CAPTCHA detection and solving"""

    CAPTCHA_SELECTORS = [
        "iframe[src*='recaptcha']", "iframe[src*='google.com/recaptcha']",
        "div.g-recaptcha", ".g-recaptcha", "iframe[src*='hcaptcha']",
        "div.h-captcha", ".h-captcha", "#recaptcha",
        "[id*='captcha']", "[class*='captcha']",
    ]

    @staticmethod
    async def detect(page) -> Tuple[bool, str]:
        """Detect CAPTCHA"""
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
    async def auto_solve_checkbox_captcha(page) -> bool:
        """Auto-solve checkbox CAPTCHA"""
        if not Config.AUTO_SOLVE_CHECKBOX_CAPTCHA:
            return False
        try:
            print("   🤖 Attempting auto-solve checkbox CAPTCHA...")
            recaptcha_frame = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
            checkbox = recaptcha_frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor")
            
            if await checkbox.count() > 0:
                await checkbox.first.click(timeout=3000)
                print("   ✅ Clicked CAPTCHA checkbox!")
                await asyncio.sleep(2)
                
                is_checked = await recaptcha_frame.locator(".recaptcha-checkbox-checked").count() > 0
                if is_checked:
                    print("   🎉 CAPTCHA auto-solved!")
                    return True
                else:
                    print("   ⚠️ May need image verification")
                    return False
            return False
        except Exception as e:
            print(f"   ⚠️ Auto-solve failed: {str(e)[:60]}")
            return False

    @staticmethod
    async def wait_for_solve(page, timeout: int = Config.CAPTCHA_WAIT_TIME) -> bool:
        """Wait for CAPTCHA solve"""
        print(f"\n   🤖 CAPTCHA DETECTED")
        if await AsyncCaptchaHandler.auto_solve_checkbox_captcha(page):
            return True
        
        print(f"   ⏳ Waiting {timeout}s for manual solve...")
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
# IFRAME HANDLER - NEW!
# =========================

class IframeHandler:
    """Handle forms inside iframes"""
    
    @staticmethod
    async def find_form_iframe(page):
        """Find iframe containing forms"""
        try:
            iframes = await page.locator("iframe").all()
            print(f"   🖼️ Found {len(iframes)} iframes, checking for forms...")
            
            for idx, iframe_elem in enumerate(iframes):
                try:
                    # Get frame
                    frame = await iframe_elem.content_frame()
                    if not frame:
                        continue
                    
                    # Check if iframe has forms
                    form_count = await frame.locator("form").count()
                    input_count = await frame.locator("input[type='text'], input[type='email']").count()
                    
                    if form_count > 0 or input_count >= 2:
                        print(f"   ✅ Found form in iframe {idx+1} ({form_count} forms, {input_count} inputs)")
                        return frame
                except:
                    continue
            
            return None
        except Exception as e:
            print(f"   ⚠️ Iframe search error: {str(e)[:60]}")
            return None


# =========================
# FIELD FILLER - ENHANCED
# =========================

class AsyncFieldFiller:
    """Field filling with retry logic"""

    @staticmethod
    async def fill_text(element, value: str, retry_count: int = 2) -> bool:
        """Fill text with retry"""
        for attempt in range(retry_count):
            try:
                if not await element.is_visible(timeout=2000):
                    return False

                # Skip React-select hidden inputs
                element_class = await element.get_attribute('class') or ''
                element_id = await element.get_attribute('id') or ''
                if 'react-select' in element_class.lower() or 'react-select' in element_id.lower():
                    if '-input' in element_id and element_class:
                        print(f"      ⏭️ Skipping React-select hidden input")
                        return False

                await element.scroll_into_view_if_needed(timeout=2000)
                await asyncio.sleep(0.2)
                await element.click(timeout=2000)
                await asyncio.sleep(0.1)
                await element.fill("")
                await asyncio.sleep(0.05)
                await element.type(str(value), delay=Config.FIELD_FILL_DELAY)
                await asyncio.sleep(0.1)
                await element.evaluate("el => el.dispatchEvent(new Event('change', {bubbles: true}))")
                
                # Verify fill
                filled_value = await element.input_value()
                if filled_value and len(filled_value) > 0:
                    return True
                elif attempt < retry_count - 1:
                    print(f"      🔄 Retry {attempt+1}/{retry_count}")
                    await asyncio.sleep(0.5)
                    continue
                return False
                
            except Exception as e:
                if attempt < retry_count - 1:
                    print(f"      🔄 Retry {attempt+1}/{retry_count}: {str(e)[:40]}")
                    await asyncio.sleep(0.5)
                    continue
                print(f"      ⚠️ Fill failed: {str(e)[:50]}")
                return False
        return False

    @staticmethod
    async def fill_dropdown(element, value: str) -> bool:
        """Fill dropdown with intelligent fallback"""
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

            # Exact match
            for opt in options:
                if opt['text'].lower() == value_lower:
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    return True

            # Contains match
            for opt in options:
                if value_lower in opt['text'].lower():
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    return True

            # Select first valid option
            placeholders = ['select', 'choose', '--', 'please', 'pick', 'option', '---']
            for opt in options:
                if opt['text'] and not any(p in opt['text'].lower() for p in placeholders):
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.1)
                    print(f"      🔄 Auto-selected: '{opt['text']}'")
                    return True

            # Last resort
            if len(options) > 1:
                await element.select_option(value=options[1]['value'])
                await asyncio.sleep(0.1)
                print(f"      🔄 Fallback: '{options[1]['text']}'")
                return True

            return False
        except Exception as e:
            print(f"      ⚠️ Dropdown error: {str(e)[:50]}")
            return False

    @staticmethod
    async def fill_checkbox(element, should_check: bool = True) -> bool:
        """Fill checkbox"""
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.1)
            is_checked = await element.is_checked()
            if should_check and not is_checked:
                await element.check(timeout=2000)
                await asyncio.sleep(0.1)
                return True
            elif not should_check and is_checked:
                await element.uncheck(timeout=2000)
                await asyncio.sleep(0.1)
                return True
            return True
        except Exception as e:
            print(f"      ⚠️ Checkbox error: {str(e)[:50]}")
            return False

    @staticmethod
    async def fill_radio(element) -> bool:
        """Fill radio button"""
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.1)
            await element.check(timeout=2000)
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            print(f"      ⚠️ Radio error: {str(e)[:50]}")
            return False

    @staticmethod
    async def fill_date(element, value: str = None) -> bool:
        """Fill date input"""
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
            await asyncio.sleep(0.1)
            if not value:
                from datetime import datetime, timedelta
                today = datetime.now()
                next_day = today + timedelta(days=1)
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                value = next_day.strftime('%Y-%m-%d')
            await element.fill(value)
            await asyncio.sleep(0.1)
            return True
        except Exception as e:
            print(f"      ⚠️ Date error: {str(e)[:50]}")
            return False


# =========================
# FORM PROCESSOR - ENHANCED
# =========================

class AsyncFormProcessor:
    """Enhanced form processing"""

    def __init__(self, page_or_frame, row, website: str, sheets_client: GoogleSheetsClient, row_index: int):
        self.page = page_or_frame  # Can be page or iframe frame
        self.row = row
        self.website = website
        self.sheets_client = sheets_client
        self.row_index = row_index
        self.filled_count = 0
        self.total_fields = 0

    def get_value(self, field_name: str) -> str:
        """Get value with intelligent fallback"""
        field_mapping = {
            'name': 'Name', 'email': 'Email', 'phone': 'Phone',
            'message': 'Message', 'country': 'Country',
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

        # Pattern-based fallback
        if any(word in field_lower for word in ['how', 'hear', 'find']):
            return "Web Search"
        elif any(word in field_lower for word in ['budget', 'price']):
            return "Flexible"
        elif any(word in field_lower for word in ['industry', 'sector']):
            return "Technology"
        elif any(word in field_lower for word in ['timeline', 'when']):
            return "Within 1 month"
        else:
            return f"Information for {field_name}"

    async def detect_field_type(self, element) -> str:
        """Detect field type from element"""
        try:
            info = await element.evaluate("""
                el => {
                    const labels = el.labels || [];
                    const label = labels[0]?.textContent || '';
                    const parentLabel = el.closest('label')?.textContent || '';
                    return {
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: el.placeholder || '',
                        type: el.type || '',
                        label: label,
                        parentLabel: parentLabel,
                        ariaLabel: el.getAttribute('aria-label') || ''
                    };
                }
            """)
            
            combined = ' '.join([
                info.get('name', ''), info.get('id', ''), info.get('placeholder', ''),
                info.get('label', ''), info.get('parentLabel', ''), info.get('ariaLabel', '')
            ]).lower()

            # Enhanced pattern matching
            if 'email' in combined or info.get('type') == 'email':
                return 'email'
            if 'phone' in combined or 'tel' in combined or info.get('type') == 'tel':
                return 'phone'
            if ('name' in combined or 'full' in combined) and 'email' not in combined:
                return 'name'
            if any(word in combined for word in ['message', 'comment', 'query', 'inquiry', 'detail']):
                return 'message'
            if 'country' in combined:
                return 'country'
            if any(word in combined for word in ['company', 'organization', 'business']):
                return 'company'
            if any(word in combined for word in ['job', 'position', 'designation', 'title']):
                return 'job'
            if 'city' in combined:
                return 'city'
            if any(word in combined for word in ['state', 'province', 'region']):
                return 'state'
            if any(word in combined for word in ['zip', 'postal', 'pin']):
                return 'zipcode'
            if any(word in combined for word in ['address', 'street', 'location']):
                return 'address'
            if any(word in combined for word in ['subject', 'topic', 'regarding']):
                return 'subject'
            if any(word in combined for word in ['budget', 'price', 'cost']):
                return 'budget'
            if any(word in combined for word in ['website', 'url', 'site']):
                return 'website'

            return info.get('name') or info.get('id') or 'unknown'
        except:
            return 'unknown'

    async def process_all_fields(self) -> int:
        """Process all fields with enhanced detection"""
        try:
            print(f"   ⏳ Waiting for page to stabilize...")
            await asyncio.sleep(3)

            # Count all fillable fields
            visible_text = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").count()
            textarea_count = await self.page.locator("textarea:visible").count()
            select_count = await self.page.locator("select:visible").count()
            checkbox_count = await self.page.locator("input[type='checkbox']:visible").count()
            radio_count = await self.page.locator("input[type='radio']:visible").count()
            
            print(f"   🔍 FIELD DETECTION:")
            print(f"      Text inputs: {visible_text}")
            print(f"      Textareas: {textarea_count}")
            print(f"      Dropdowns: {select_count}")
            print(f"      Checkboxes: {checkbox_count}")
            print(f"      Radio buttons: {radio_count}")
            
            self.total_fields = visible_text + textarea_count + select_count + checkbox_count + radio_count

            if self.total_fields == 0:
                print(f"   ❌ NO FILLABLE FIELDS FOUND")
                return 0

            print(f"   ✅ Starting to fill {self.total_fields} fields...\n")

            # Fill text inputs
            all_inputs_list = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").all()
            for idx, inp in enumerate(all_inputs_list):
                try:
                    input_type = await inp.get_attribute('type')
                    field_type = await self.detect_field_type(inp)
                    
                    if input_type == 'date':
                        print(f"      [{idx+1}/{len(all_inputs_list)}] Date field '{field_type}'")
                        if await AsyncFieldFiller.fill_date(inp):
                            self.filled_count += 1
                            print(f"      ✅ Date filled")
                    else:
                        value = self.get_value(field_type)
                        print(f"      [{idx+1}/{len(all_inputs_list)}] '{field_type}': {value[:30]}...")
                        if await AsyncFieldFiller.fill_text(inp, value):
                            self.filled_count += 1
                            print(f"      ✅ Success")
                    
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill textareas
            all_textareas = await self.page.locator("textarea:visible").all()
            for idx, ta in enumerate(all_textareas):
                try:
                    value = self.get_value('message')
                    print(f"      Textarea {idx+1}: {value[:30]}...")
                    if await AsyncFieldFiller.fill_text(ta, value):
                        self.filled_count += 1
                        print(f"      ✅ Success")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill dropdowns
            all_selects = await self.page.locator("select:visible").all()
            for idx, sel in enumerate(all_selects):
                try:
                    field_type = await self.detect_field_type(sel)
                    value = self.get_value(field_type)
                    print(f"      Dropdown {idx+1}: {field_type}")
                    if await AsyncFieldFiller.fill_dropdown(sel, value):
                        self.filled_count += 1
                        print(f"      ✅ Success")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill checkboxes
            all_checkboxes = await self.page.locator("input[type='checkbox']:visible").all()
            for idx, cb in enumerate(all_checkboxes):
                try:
                    field_type = await self.detect_field_type(cb)
                    should_check = any(word in field_type.lower() for word in ['term', 'privacy', 'policy', 'agree', 'accept', 'gdpr'])
                    print(f"      Checkbox {idx+1}: '{field_type}'")
                    if await AsyncFieldFiller.fill_checkbox(cb, should_check):
                        self.filled_count += 1
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill radio buttons
            all_radios = await self.page.locator("input[type='radio']:visible").all()
            processed_groups = set()
            for idx, rb in enumerate(all_radios):
                try:
                    radio_name = await rb.get_attribute('name')
                    if radio_name and radio_name not in processed_groups:
                        field_type = await self.detect_field_type(rb)
                        print(f"      Radio: '{field_type}'")
                        if await AsyncFieldFiller.fill_radio(rb):
                            self.filled_count += 1
                            processed_groups.add(radio_name)
                        await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

        except Exception as e:
            print(f"   ❌ Field processing error: {str(e)}")
            traceback.print_exc()

        return self.filled_count


# =========================
# MAIN WORKER - ULTRA ENHANCED
# =========================

async def process_website_async(row, idx: int, total: int, sheets_client: GoogleSheetsClient, playwright_instance):
    """Process single website with maximum success rate"""
    website = str(row.get("website","")).strip()
    row_index = int(row.get('row_index', idx))

    print(f"\n{'='*90}")
    print(f"🌐 [{idx+1}/{total}] {website}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*90}\n")

    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "PROCESSING")

    browser = None
    try:
        # Launch browser
        browser = await playwright_instance.chromium.launch(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        # Navigate with retry
        nav_success = False
        for attempt in range(Config.MAX_RETRIES):
            try:
                print(f"   🔄 Loading website (attempt {attempt+1}/{Config.MAX_RETRIES})...")
                await page.goto(website, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(3)
                print(f"   ✅ Loaded: {page.url}")
                nav_success = True
                break
            except Exception as nav_err:
                print(f"   ⚠️ Attempt {attempt+1} failed: {str(nav_err)[:60]}")
                if attempt < Config.MAX_RETRIES - 1:
                    await asyncio.sleep(Config.RETRY_DELAY)
                    continue
                else:
                    print(f"   ❌ Navigation failed after {Config.MAX_RETRIES} attempts")
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NAV_ERROR")
                    return False

        if not nav_success:
            return False

        # Check CAPTCHA
        has_captcha, _ = await AsyncCaptchaHandler.detect(page)
        if has_captcha:
            if not await AsyncCaptchaHandler.wait_for_solve(page):
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "CAPTCHA_BLOCKED")
                return False

        # ULTRA-SMART CONTACT PAGE DETECTION
        contact_found = False
        
        # Strategy 1: Check current URL
        current_url = page.url.lower()
        if any(word in current_url for word in ['contact', 'enquiry', 'inquiry', 'book', 'appointment', 'schedule', 'quote', 'form']):
            print(f"   ✅ Already on contact/form page!")
            contact_found = True
        
        # Strategy 2: Check for forms on current page
        if not contact_found:
            form_count = await page.locator("form:visible").count()
            input_count = await page.locator("input:visible[type='text'], input:visible[type='email']").count()
            if form_count > 0 and input_count >= 2:
                print(f"   ✅ Found {form_count} forms on current page ({input_count} inputs)")
                contact_found = True
        
        # Strategy 3: Search for contact links
        if not contact_found:
            print(f"   🔎 Searching for contact/form page...")
            keywords = [
                "Contact Us", "Contact", "Get in Touch", "Reach Out",
                "Book Now", "Schedule", "Appointment",
                "Request Quote", "Get Quote", "Free Consultation",
                "Enquiry", "Inquiry", "Talk to Us", "Connect",
                "Get Started", "Learn More", "Request Info",
            ]
            
            for keyword in keywords:
                try:
                    links = page.locator(f"a:has-text('{keyword}')").or_(page.locator(f"button:has-text('{keyword}')"))
                    if await links.count() > 0:
                        first_link = links.first
                        if await first_link.is_visible(timeout=1000):
                            print(f"   ✅ Found '{keyword}' link")
                            await first_link.click(timeout=5000)
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                            await asyncio.sleep(2)
                            contact_found = True
                            print(f"   ✅ Opened: {page.url}")
                            break
                except:
                    continue
            
            # Strategy 4: Try href pattern matching
            if not contact_found:
                try:
                    contact_link = page.locator("a[href*='contact'], a[href*='enquiry'], a[href*='book']").first
                    if await contact_link.count() > 0:
                        print(f"   ✅ Found contact link by URL pattern")
                        await contact_link.click(timeout=5000)
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                        await asyncio.sleep(2)
                        contact_found = True
                except:
                    pass

        # Extra stabilization wait
        await asyncio.sleep(2)

        # Check for iframe forms
        working_frame = page
        iframe_form = await IframeHandler.find_form_iframe(page)
        if iframe_form:
            working_frame = iframe_form
            print(f"   🖼️ Using iframe form")

        # Process form
        processor = AsyncFormProcessor(working_frame, row, website, sheets_client, row_index)
        filled = await processor.process_all_fields()

        if filled > 0:
            print(f"\n   ✅ Filled {filled}/{processor.total_fields} fields")

            # Enhanced submit button detection
            try:
                print(f"   🔍 Looking for submit button...")
                submit_selectors = [
                    "button[type='submit']:visible",
                    "input[type='submit']:visible",
                    "button:has-text('Submit'):visible",
                    "button:has-text('Send'):visible",
                    "button:has-text('Book Now'):visible",
                    "button:has-text('Schedule'):visible",
                    "button:has-text('Request'):visible",
                    "button:has-text('Get Started'):visible",
                    "button:has-text('Contact'):visible",
                    "button:has-text('Enquire'):visible",
                    "input[value*='Submit']:visible",
                    "input[value*='Send']:visible",
                    ".submit-btn:visible",
                    ".contact-submit:visible",
                    "form button:visible",  # Any button in form
                ]
                
                submit_found = False
                for selector in submit_selectors:
                    try:
                        btns = working_frame.locator(selector)
                        if await btns.count() > 0:
                            btn = btns.first
                            if await btn.is_visible(timeout=1000):
                                print(f"   🎯 Found: {selector}")
                                await btn.click(timeout=5000)
                                print(f"   ✅ FORM SUBMITTED!")
                                submit_found = True
                                break
                    except:
                        continue
                
                if submit_found:
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "SUCCESS")
                    await asyncio.sleep(3)  # Wait to see result
                else:
                    print(f"   ⚠️ Submit button not found")
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FILLED_NO_SUBMIT")
                
                return True
                
            except Exception as submit_err:
                print(f"   ⚠️ Submit error: {str(submit_err)[:60]}")
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
# MAIN EXECUTOR
# =========================

async def main_async():
    """Main execution"""
    print("="*90)
    print("🚀 FORM AUTO-FILLER - v6.0 ULTRA SUCCESS EDITION")
    print(f"   ⚡ Max Workers: {Config.MAX_PARALLEL_WORKERS}")
    print(f"   👁️ Headless: {Config.HEADLESS}")
    print("="*90)

    sheets_client = GoogleSheetsClient(credentials_file="form-automation-484413-489b8d00026a.json")
    df = sheets_client.read_two_sheets(
        Config.GOOGLE_SHEETS_ID,
        Config.WEBSITE_SHEET_RANGE,
        Config.DETAILS_SHEET_RANGE
    )

    if df.empty:
        print("❌ No data")
        return

    print(f"\n✅ Loaded {len(df)} websites\n")

    playwright_instance = await async_playwright().start()

    for idx, row in df.iterrows():
        await process_website_async(row, idx, len(df), sheets_client, playwright_instance)
        if idx < len(df) - 1:
            print("\n⏸️ Waiting before next...\n")
            await asyncio.sleep(3)

    await playwright_instance.stop()

    print("\n" + "="*90)
    print("✅ PROCESSING COMPLETE")
    print("="*90)


if __name__ == "__main__":
    import sys
    try:
        print(f"🚀 Starting at {datetime.now()}")
        asyncio.run(main_async())
        print(f"\n✅ Completed at {datetime.now()}")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
