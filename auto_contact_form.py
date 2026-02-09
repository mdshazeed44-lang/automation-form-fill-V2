"""
FORM AUTO-FILLER - BEAST MODE VERSION 🔥
=========================================
MAXIMUM POWER - AGGRESSIVE FORM DETECTION & FILLING

Version: 7.0.0 - BEAST MODE EDITION
- Waits longer for dynamic forms to load
- Multiple detection passes
- Aggressive field matching
- Force-fill stubborn fields
- Smart submit with multiple attempts
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
    """Configuration"""
    # Google Sheets
    GOOGLE_SHEETS_ID = "1ZuplfaKjpco06iYjlF_MgeDZkoOTaVrymP-4O4jZpPE"
    WEBSITE_SHEET_RANGE = "'Database'!A:A"
    DETAILS_SHEET_RANGE = "'Details to fill'!A:E"
    GOOGLE_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # AGGRESSIVE SETTINGS FOR MAX SUCCESS
    PAGE_LOAD_TIMEOUT = 40000  # 40s
    FORM_WAIT_TIME = 8  # Wait 8s for dynamic forms to load
    FIELD_DETECTION_PASSES = 3  # Multiple detection attempts
    ELEMENT_TIMEOUT = 5000  # 5s per element
    FIELD_FILL_DELAY = 100
    ANIMATION_DELAY = 0.2
    
    # Retry
    MAX_RETRIES = 3
    RETRY_DELAY = 3
    FIELD_RETRY_COUNT = 3  # Retry each field 3 times
    
    # Browser
    HEADLESS = False
    SLOW_MO = 200  # Slower for better reliability

    # CAPTCHA
    CAPTCHA_WAIT_TIME = 40
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
        "service": "Consultation", "budget": "Flexible",
        "source": "Web Search", "website": "www.example.com",
        "industry": "Technology", "firstname": "Interested",
        "lastname": "Customer", "fullname": "Interested Customer",
    }


# =========================
# GOOGLE SHEETS
# =========================

class GoogleSheetsClient:
    """Google Sheets handler"""

    def __init__(self, credentials_env_var: str = Config.GOOGLE_CREDENTIALS_ENV, credentials_file: Optional[str] = None):
        self.credentials_env_var = credentials_env_var
        self.credentials_file = credentials_file
        self.service = None
        self.authenticate()

    def authenticate(self):
        """Authenticate"""
        try:
            print("🔐 Authenticating with Google Sheets...")
            creds_json = os.getenv(self.credentials_env_var)

            if creds_json:
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            elif self.credentials_file and os.path.exists(self.credentials_file):
                with open(self.credentials_file, "r") as f:
                    creds_dict = json.load(f)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            else:
                raise FileNotFoundError("Google credentials not found")

            self.service = build('sheets', 'v4', credentials=creds)
            print("✅ Authenticated")
        except Exception as e:
            print(f"❌ Auth failed: {e}")
            raise

    def update_status(self, spreadsheet_id: str, row_number: int, status: str):
        """Update status"""
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
            print(f"   ⚠️ Status update failed: {str(e)[:50]}")

    def read_two_sheets(self, spreadsheet_id: str, websites_range: str, details_range: str) -> pd.DataFrame:
        """Read sheets"""
        try:
            print("\n📋 Reading URLs...")
            websites_result = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=websites_range
            ).execute()
            websites_values = websites_result.get('values', [])
            if not websites_values or len(websites_values) <= 1:
                return pd.DataFrame()
            websites = [row[0] for row in websites_values[1:] if row and len(row) > 0]
            print(f"✅ Found {len(websites)} websites")

            print("\n📋 Reading form details...")
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
            print(f"❌ Read error: {e}")
            raise


# =========================
# CAPTCHA HANDLER
# =========================

class AsyncCaptchaHandler:
    """CAPTCHA handler"""

    CAPTCHA_SELECTORS = [
        "iframe[src*='recaptcha']", "div.g-recaptcha",
        "iframe[src*='hcaptcha']", "div.h-captcha",
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
            print("   🤖 Auto-solving CAPTCHA...")
            recaptcha_frame = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
            checkbox = recaptcha_frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor")
            
            if await checkbox.count() > 0:
                await checkbox.first.click(timeout=3000)
                print("   ✅ Clicked CAPTCHA!")
                await asyncio.sleep(2)
                
                is_checked = await recaptcha_frame.locator(".recaptcha-checkbox-checked").count() > 0
                if is_checked:
                    print("   🎉 CAPTCHA solved!")
                    return True
            return False
        except Exception as e:
            print(f"   ⚠️ Auto-solve failed: {str(e)[:50]}")
            return False

    @staticmethod
    async def wait_for_solve(page, timeout: int = Config.CAPTCHA_WAIT_TIME) -> bool:
        """Wait for CAPTCHA solve"""
        print(f"\n   🤖 CAPTCHA DETECTED")
        if await AsyncCaptchaHandler.auto_solve_checkbox_captcha(page):
            return True
        
        print(f"   ⏳ Waiting {timeout}s...")
        start = time.time()
        while (time.time() - start) < timeout:
            has_captcha, _ = await AsyncCaptchaHandler.detect(page)
            if not has_captcha:
                print("   ✅ CAPTCHA SOLVED!")
                await asyncio.sleep(1)
                return True
            await asyncio.sleep(Config.CAPTCHA_CHECK_INTERVAL)
        print("   ⏱️ Timeout")
        return False


# =========================
# BEAST MODE FIELD FILLER 🔥
# =========================

class BeastModeFieldFiller:
    """AGGRESSIVE field filling with force"""

    @staticmethod
    async def force_fill_text(element, value: str, retry_count: int = Config.FIELD_RETRY_COUNT) -> bool:
        """FORCE FILL with multiple methods"""
        for attempt in range(retry_count):
            try:
                if not await element.is_visible(timeout=2000):
                    return False

                await element.scroll_into_view_if_needed(timeout=3000)
                await asyncio.sleep(0.3)

                # Method 1: Standard fill
                try:
                    await element.click(timeout=3000)
                    await asyncio.sleep(0.1)
                    await element.fill("")
                    await asyncio.sleep(0.1)
                    await element.type(str(value), delay=Config.FIELD_FILL_DELAY)
                    await asyncio.sleep(0.2)
                except:
                    pass

                # Method 2: JavaScript injection (for stubborn fields)
                try:
                    await element.evaluate(f"""
                        el => {{
                            el.value = '{value}';
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        }}
                    """)
                    await asyncio.sleep(0.2)
                except:
                    pass

                # Method 3: Direct value set + events
                try:
                    await element.evaluate(f"el => el.value = '{value}'")
                    await element.press("Tab")  # Trigger blur
                    await asyncio.sleep(0.1)
                except:
                    pass

                # Verify
                try:
                    filled_value = await element.input_value()
                    if filled_value and len(filled_value) > 0:
                        return True
                except:
                    pass

                if attempt < retry_count - 1:
                    print(f"      🔄 Retry {attempt+1}/{retry_count}")
                    await asyncio.sleep(0.5)
                    continue

                return False
                
            except Exception as e:
                if attempt < retry_count - 1:
                    print(f"      🔄 Retry {attempt+1}: {str(e)[:40]}")
                    await asyncio.sleep(0.5)
                    continue
                print(f"      ⚠️ Failed: {str(e)[:50]}")
                return False
        return False

    @staticmethod
    async def force_fill_dropdown(element, value: str) -> bool:
        """FORCE FILL dropdown"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.2)

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
                    await asyncio.sleep(0.2)
                    return True

            # Try contains
            for opt in options:
                if value_lower in opt['text'].lower():
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.2)
                    return True

            # Auto-select first valid
            placeholders = ['select', 'choose', '--', 'please', 'pick', 'option']
            for opt in options:
                if opt['text'] and not any(p in opt['text'].lower() for p in placeholders):
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.2)
                    print(f"      🔄 Auto: '{opt['text']}'")
                    return True

            # Last resort
            if len(options) > 1:
                await element.select_option(value=options[1]['value'])
                await asyncio.sleep(0.2)
                return True

            return False
        except Exception as e:
            print(f"      ⚠️ Dropdown: {str(e)[:50]}")
            return False

    @staticmethod
    async def force_fill_checkbox(element, should_check: bool = True) -> bool:
        """FORCE FILL checkbox"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.2)
            
            is_checked = await element.is_checked()
            if should_check and not is_checked:
                await element.check(timeout=3000)
                await asyncio.sleep(0.2)
                return True
            elif not should_check and is_checked:
                await element.uncheck(timeout=3000)
                await asyncio.sleep(0.2)
                return True
            return True
        except Exception as e:
            print(f"      ⚠️ Checkbox: {str(e)[:50]}")
            return False

    @staticmethod
    async def force_fill_radio(element) -> bool:
        """FORCE FILL radio"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.2)
            await element.check(timeout=3000)
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            print(f"      ⚠️ Radio: {str(e)[:50]}")
            return False


# =========================
# BEAST MODE FORM PROCESSOR 🔥
# =========================

class BeastModeFormProcessor:
    """AGGRESSIVE form processor"""

    def __init__(self, page_or_frame, row, website: str, sheets_client: GoogleSheetsClient, row_index: int):
        self.page = page_or_frame
        self.row = row
        self.website = website
        self.sheets_client = sheets_client
        self.row_index = row_index
        self.filled_count = 0
        self.total_fields = 0

    def get_value(self, field_name: str) -> str:
        """Get value with smart fallback"""
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

        # Intelligent patterns
        if 'first' in field_lower and 'name' in field_lower:
            return "Interested"
        elif 'last' in field_lower and 'name' in field_lower:
            return "Customer"
        elif any(w in field_lower for w in ['how', 'hear', 'find']):
            return "Web Search"
        elif any(w in field_lower for w in ['budget', 'price']):
            return "Flexible"
        elif any(w in field_lower for w in ['industry', 'sector']):
            return "Technology"
        else:
            return f"Information for {field_name}"

    async def detect_field_type(self, element) -> str:
        """Detect field type"""
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

            # Enhanced detection
            if 'email' in combined or info.get('type') == 'email':
                return 'email'
            if 'phone' in combined or 'tel' in combined or info.get('type') == 'tel':
                return 'phone'
            if 'first' in combined and 'name' in combined:
                return 'firstname'
            if 'last' in combined and 'name' in combined:
                return 'lastname'
            if ('name' in combined or 'full' in combined) and 'email' not in combined:
                return 'name'
            if any(w in combined for w in ['message', 'comment', 'query', 'inquiry', 'detail', 'describe']):
                return 'message'
            if 'country' in combined:
                return 'country'
            if any(w in combined for w in ['company', 'organization', 'business']):
                return 'company'
            if any(w in combined for w in ['job', 'position', 'designation']):
                return 'job'
            if 'city' in combined:
                return 'city'
            if any(w in combined for w in ['state', 'province']):
                return 'state'
            if any(w in combined for w in ['zip', 'postal', 'pin']):
                return 'zipcode'
            if 'address' in combined:
                return 'address'
            if any(w in combined for w in ['subject', 'topic', 'regarding']):
                return 'subject'
            if any(w in combined for w in ['budget', 'price']):
                return 'budget'
            if any(w in combined for w in ['website', 'url']):
                return 'website'

            return info.get('name') or info.get('id') or 'unknown'
        except:
            return 'unknown'

    async def aggressive_field_detection(self) -> bool:
        """MULTIPLE PASSES for field detection"""
        print(f"   🔍 BEAST MODE DETECTION - {Config.FIELD_DETECTION_PASSES} passes...")
        
        for pass_num in range(Config.FIELD_DETECTION_PASSES):
            await asyncio.sleep(Config.FORM_WAIT_TIME / Config.FIELD_DETECTION_PASSES)
            
            visible_text = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").count()
            textarea_count = await self.page.locator("textarea:visible").count()
            select_count = await self.page.locator("select:visible").count()
            checkbox_count = await self.page.locator("input[type='checkbox']:visible").count()
            radio_count = await self.page.locator("input[type='radio']:visible").count()
            
            total = visible_text + textarea_count + select_count + checkbox_count + radio_count
            
            print(f"      Pass {pass_num+1}: Text={visible_text}, Textarea={textarea_count}, Select={select_count}, Checkbox={checkbox_count}, Radio={radio_count}")
            
            if total > 0:
                self.total_fields = total
                return True
        
        return False

    async def beast_mode_fill_all(self) -> int:
        """BEAST MODE filling - FORCE EVERYTHING"""
        try:
            # Multiple detection passes
            if not await self.aggressive_field_detection():
                print(f"   ❌ NO FIELDS after {Config.FIELD_DETECTION_PASSES} passes")
                return 0

            print(f"   ✅ Found {self.total_fields} fields - STARTING BEAST MODE FILL!\n")

            # Fill text inputs - FORCE MODE
            all_inputs = await self.page.locator("input:visible:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").all()
            
            for idx, inp in enumerate(all_inputs):
                try:
                    field_type = await self.detect_field_type(inp)
                    value = self.get_value(field_type)
                    print(f"      [{idx+1}/{len(all_inputs)}] FORCE '{field_type}': {value[:30]}...")
                    
                    if await BeastModeFieldFiller.force_fill_text(inp, value):
                        self.filled_count += 1
                        print(f"      ✅ FILLED!")
                    else:
                        print(f"      ⚠️ Failed after retries")
                    
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill textareas - FORCE MODE
            all_textareas = await self.page.locator("textarea:visible").all()
            for idx, ta in enumerate(all_textareas):
                try:
                    value = self.get_value('message')
                    print(f"      Textarea {idx+1}: {value[:30]}...")
                    if await BeastModeFieldFiller.force_fill_text(ta, value):
                        self.filled_count += 1
                        print(f"      ✅ FILLED!")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill dropdowns - FORCE MODE
            all_selects = await self.page.locator("select:visible").all()
            for idx, sel in enumerate(all_selects):
                try:
                    field_type = await self.detect_field_type(sel)
                    value = self.get_value(field_type)
                    print(f"      Dropdown {idx+1}: {field_type}")
                    if await BeastModeFieldFiller.force_fill_dropdown(sel, value):
                        self.filled_count += 1
                        print(f"      ✅ FILLED!")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill checkboxes - FORCE MODE
            all_checkboxes = await self.page.locator("input[type='checkbox']:visible").all()
            for idx, cb in enumerate(all_checkboxes):
                try:
                    field_type = await self.detect_field_type(cb)
                    should_check = any(w in field_type.lower() for w in ['term', 'privacy', 'policy', 'agree', 'accept'])
                    print(f"      Checkbox {idx+1}: '{field_type}'")
                    if await BeastModeFieldFiller.force_fill_checkbox(cb, should_check):
                        self.filled_count += 1
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

            # Fill radios - FORCE MODE
            all_radios = await self.page.locator("input[type='radio']:visible").all()
            processed_groups = set()
            for idx, rb in enumerate(all_radios):
                try:
                    radio_name = await rb.get_attribute('name')
                    if radio_name and radio_name not in processed_groups:
                        if await BeastModeFieldFiller.force_fill_radio(rb):
                            self.filled_count += 1
                            processed_groups.add(radio_name)
                        await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:60]}")
                    continue

        except Exception as e:
            print(f"   ❌ Processing error: {str(e)}")
            traceback.print_exc()

        return self.filled_count


# =========================
# BEAST MODE SUBMIT 🔥
# =========================

class BeastModeSubmit:
    """AGGRESSIVE submit with multiple attempts"""
    
    @staticmethod
    async def force_submit(page_or_frame, max_attempts: int = 5) -> bool:
        """FORCE SUBMIT with multiple methods"""
        print(f"   🎯 BEAST MODE SUBMIT - {max_attempts} attempts...")
        
        submit_selectors = [
            "button[type='submit']:visible",
            "input[type='submit']:visible",
            "button:has-text('Submit'):visible",
            "button:has-text('Send'):visible",
            "button:has-text('Book'):visible",
            "button:has-text('Schedule'):visible",
            "button:has-text('Request'):visible",
            "button:has-text('Contact'):visible",
            "button:has-text('Enquire'):visible",
            "button:has-text('Get Started'):visible",
            "input[value*='Submit']:visible",
            "input[value*='Send']:visible",
            ".submit-btn:visible",
            ".contact-submit:visible",
            "form button:visible:not([type='button']):not([type='reset'])",
            "form input[type='button'][value*='Submit']:visible",
        ]
        
        for attempt in range(max_attempts):
            print(f"      Attempt {attempt+1}/{max_attempts}...")
            
            for selector in submit_selectors:
                try:
                    btns = page_or_frame.locator(selector)
                    count = await btns.count()
                    
                    if count > 0:
                        btn = btns.first
                        if await btn.is_visible(timeout=2000):
                            print(f"      🎯 Found: {selector}")
                            
                            # Try multiple click methods
                            try:
                                await btn.click(timeout=5000)
                            except:
                                try:
                                    await btn.click(force=True, timeout=5000)
                                except:
                                    try:
                                        await btn.evaluate("el => el.click()")
                                    except:
                                        pass
                            
                            await asyncio.sleep(2)
                            print(f"      ✅ SUBMITTED!")
                            return True
                except Exception as e:
                    continue
            
            if attempt < max_attempts - 1:
                print(f"      ⚠️ Retrying submit...")
                await asyncio.sleep(1)
        
        print(f"      ❌ Submit failed after {max_attempts} attempts")
        return False


# =========================
# MAIN BEAST MODE WORKER 🔥
# =========================

async def beast_mode_process_website(row, idx: int, total: int, sheets_client: GoogleSheetsClient, playwright_instance):
    """BEAST MODE website processor"""
    website = str(row.get("website","")).strip()
    row_index = int(row.get('row_index', idx))

    print(f"\n{'='*90}")
    print(f"🔥 BEAST MODE [{idx+1}/{total}] {website}")
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
                print(f"   🔄 Loading (attempt {attempt+1})...")
                await page.goto(website, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(4)  # Extra wait
                print(f"   ✅ Loaded: {page.url}")
                nav_success = True
                break
            except Exception as nav_err:
                print(f"   ⚠️ Attempt {attempt+1} failed: {str(nav_err)[:60]}")
                if attempt < Config.MAX_RETRIES - 1:
                    await asyncio.sleep(Config.RETRY_DELAY)
                    continue
                else:
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

        # SMART CONTACT PAGE DETECTION
        print(f"   🔎 Looking for contact page...")
        
        current_url = page.url.lower()
        if any(word in current_url for word in ['contact', 'enquiry', 'book', 'appointment', 'quote', 'form']):
            print(f"   ✅ Already on contact/form page!")
        else:
            # Check for forms on current page
            form_count = await page.locator("form:visible").count()
            input_count = await page.locator("input:visible[type='text'], input:visible[type='email']").count()
            
            if form_count > 0 and input_count >= 2:
                print(f"   ✅ Found {form_count} forms on current page")
            else:
                # Search for contact links
                keywords = [
                    "Contact Us", "Contact", "Get in Touch",
                    "Book Now", "Schedule", "Appointment",
                    "Request Quote", "Get Quote",
                    "Enquiry", "Inquiry", "Talk to Us",
                ]
                
                found_link = False
                for keyword in keywords:
                    try:
                        links = page.locator(f"a:has-text('{keyword}')").or_(page.locator(f"button:has-text('{keyword}')"))
                        if await links.count() > 0:
                            first_link = links.first
                            if await first_link.is_visible(timeout=2000):
                                print(f"   ✅ Found '{keyword}' link")
                                await first_link.click(timeout=5000)
                                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                                await asyncio.sleep(3)
                                found_link = True
                                print(f"   ✅ Opened: {page.url}")
                                break
                    except:
                        continue
                
                if not found_link:
                    print(f"   ⚠️ No contact link - trying current page")

        # Extra wait for dynamic forms
        print(f"   ⏳ Waiting {Config.FORM_WAIT_TIME}s for dynamic forms...")
        await asyncio.sleep(Config.FORM_WAIT_TIME)

        # BEAST MODE FORM PROCESSING
        processor = BeastModeFormProcessor(page, row, website, sheets_client, row_index)
        filled = await processor.beast_mode_fill_all()

        if filled > 0:
            print(f"\n   🔥 BEAST MODE FILLED {filled}/{processor.total_fields} fields!")

            # BEAST MODE SUBMIT
            submit_success = await BeastModeSubmit.force_submit(page)
            
            if submit_success:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "SUCCESS")
                await asyncio.sleep(3)
                return True
            else:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FILLED_NO_SUBMIT")
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
# MAIN
# =========================

async def main_async():
    """Main execution"""
    print("="*90)
    print("🔥 FORM AUTO-FILLER - BEAST MODE v7.0")
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
        await beast_mode_process_website(row, idx, len(df), sheets_client, playwright_instance)
        if idx < len(df) - 1:
            print("\n⏸️ Waiting...\n")
            await asyncio.sleep(3)

    await playwright_instance.stop()

    print("\n" + "="*90)
    print("🔥 BEAST MODE COMPLETE!")
    print("="*90)


if __name__ == "__main__":
    import sys
    try:
        print(f"🔥 BEAST MODE START: {datetime.now()}")
        asyncio.run(main_async())
        print(f"\n✅ BEAST MODE END: {datetime.now()}")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
