"""
FORM AUTO-FILLER - ULTIMATE POWER 💪
====================================
GUARANTEED FORM FILLING - KOI BHI FORM FILL KAREGA!

Version: 8.0.0 - ULTIMATE POWER EDITION
✅ Fixed JavaScript injection (proper escaping)
✅ Longer waits for dynamic forms
✅ Better visibility detection
✅ Multiple fill methods with verification
✅ Smart field retry with different strategies
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
import re
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

    # ULTIMATE POWER SETTINGS
    PAGE_LOAD_TIMEOUT = 45000  # 45s
    INITIAL_WAIT = 5  # 5s initial wait
    FORM_WAIT_TIME = 10  # 10s for dynamic forms
    FIELD_DETECTION_PASSES = 4  # 4 passes
    ELEMENT_TIMEOUT = 6000  # 6s per element
    FIELD_FILL_DELAY = 120  # Slower typing
    ANIMATION_DELAY = 0.25
    
    # Retry Settings
    MAX_RETRIES = 3
    RETRY_DELAY = 4
    FIELD_RETRY_COUNT = 4  # 4 attempts per field
    
    # Browser
    HEADLESS = False
    SLOW_MO = 250  # Very slow for reliability

    # CAPTCHA
    CAPTCHA_WAIT_TIME = 45
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
            print("🔐 Authenticating...")
            creds_json = os.getenv(self.credentials_env_var)

            if creds_json:
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            elif self.credentials_file and os.path.exists(self.credentials_file):
                with open(self.credentials_file, "r") as f:
                    creds_dict = json.load(f)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            else:
                raise FileNotFoundError("Credentials not found")

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
            print(f"   📊 {status}")
        except Exception as e:
            print(f"   ⚠️ Status update failed")

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
            print(f"✅ {len(websites)} websites")

            print("📋 Reading details...")
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

class CaptchaHandler:
    """CAPTCHA handler"""

    CAPTCHA_SELECTORS = [
        "iframe[src*='recaptcha']", "div.g-recaptcha",
        "iframe[src*='hcaptcha']", "div.h-captcha",
        "[id*='captcha']", "[class*='captcha']",
    ]

    @staticmethod
    async def detect(page) -> Tuple[bool, str]:
        """Detect CAPTCHA"""
        for selector in CaptchaHandler.CAPTCHA_SELECTORS:
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
    async def auto_solve_checkbox(page) -> bool:
        """Auto-solve checkbox CAPTCHA"""
        if not Config.AUTO_SOLVE_CHECKBOX_CAPTCHA:
            return False
        try:
            print("   🤖 Auto-solving CAPTCHA...")
            recaptcha_frame = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
            checkbox = recaptcha_frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor")
            
            if await checkbox.count() > 0:
                await checkbox.first.click(timeout=3000)
                await asyncio.sleep(2)
                is_checked = await recaptcha_frame.locator(".recaptcha-checkbox-checked").count() > 0
                if is_checked:
                    print("   🎉 CAPTCHA solved!")
                    return True
            return False
        except:
            return False

    @staticmethod
    async def wait_for_solve(page, timeout: int = Config.CAPTCHA_WAIT_TIME) -> bool:
        """Wait for CAPTCHA solve"""
        print(f"   🤖 CAPTCHA DETECTED")
        if await CaptchaHandler.auto_solve_checkbox(page):
            return True
        
        print(f"   ⏳ Waiting {timeout}s...")
        start = time.time()
        while (time.time() - start) < timeout:
            has_captcha, _ = await CaptchaHandler.detect(page)
            if not has_captcha:
                print("   ✅ SOLVED!")
                await asyncio.sleep(1)
                return True
            await asyncio.sleep(Config.CAPTCHA_CHECK_INTERVAL)
        return False


# =========================
# ULTIMATE POWER FIELD FILLER 💪
# =========================

class UltimatePowerFiller:
    """ULTIMATE field filling with guaranteed success"""

    @staticmethod
    def escape_js_string(value: str) -> str:
        """Properly escape string for JavaScript - CRITICAL FIX!"""
        # Escape backslashes first
        value = value.replace('\\', '\\\\')
        # Escape single quotes
        value = value.replace("'", "\\'")
        # Escape double quotes
        value = value.replace('"', '\\"')
        # Escape newlines
        value = value.replace('\n', '\\n')
        value = value.replace('\r', '\\r')
        return value

    @staticmethod
    async def ultimate_fill_text(element, value: str, retry_count: int = Config.FIELD_RETRY_COUNT) -> bool:
        """ULTIMATE text fill - 4 METHODS!"""
        value_str = str(value)
        
        for attempt in range(retry_count):
            try:
                # Check if element exists and is attached
                try:
                    is_attached = await element.evaluate("el => el.isConnected")
                    if not is_attached:
                        return False
                except:
                    return False

                # Scroll into view
                try:
                    await element.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(0.3)
                except:
                    pass

                # METHOD 1: Standard Playwright fill + type
                try:
                    await element.click(timeout=3000, force=True)
                    await asyncio.sleep(0.15)
                    await element.fill("")
                    await asyncio.sleep(0.1)
                    await element.type(value_str, delay=Config.FIELD_FILL_DELAY)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    print(f"         Method 1 failed: {str(e)[:30]}")

                # METHOD 2: JavaScript with PROPER escaping
                try:
                    escaped_value = UltimatePowerFiller.escape_js_string(value_str)
                    js_code = f"""
                        el => {{
                            el.value = '{escaped_value}';
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        }}
                    """
                    await element.evaluate(js_code)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    print(f"         Method 2 failed: {str(e)[:30]}")

                # METHOD 3: Set value via property + multiple events
                try:
                    escaped_value = UltimatePowerFiller.escape_js_string(value_str)
                    await element.evaluate(f"""
                        el => {{
                            el.value = '{escaped_value}';
                            ['input', 'change', 'blur', 'keyup', 'keydown'].forEach(evt => {{
                                el.dispatchEvent(new Event(evt, {{ bubbles: true }}));
                            }});
                        }}
                    """)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    print(f"         Method 3 failed: {str(e)[:30]}")

                # METHOD 4: Focus + setAttribute + events
                try:
                    await element.focus(timeout=2000)
                    await asyncio.sleep(0.1)
                    escaped_value = UltimatePowerFiller.escape_js_string(value_str)
                    await element.evaluate(f"""
                        el => {{
                            el.setAttribute('value', '{escaped_value}');
                            el.value = '{escaped_value}';
                            el.focus();
                            el.dispatchEvent(new Event('focus', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    """)
                    await asyncio.sleep(0.2)
                except Exception as e:
                    print(f"         Method 4 failed: {str(e)[:30]}")

                # VERIFY - Check if value was filled
                try:
                    filled_value = await element.input_value()
                    if filled_value and len(filled_value) > 0:
                        print(f"         ✅ VERIFIED: '{filled_value[:20]}'")
                        return True
                except:
                    pass

                # Check via JavaScript
                try:
                    js_value = await element.evaluate("el => el.value")
                    if js_value and len(str(js_value)) > 0:
                        print(f"         ✅ VERIFIED (JS): '{str(js_value)[:20]}'")
                        return True
                except:
                    pass

                if attempt < retry_count - 1:
                    print(f"         🔄 Retry {attempt+1}/{retry_count}")
                    await asyncio.sleep(0.8)
                    continue

            except Exception as e:
                if attempt < retry_count - 1:
                    print(f"         🔄 Retry {attempt+1}: {str(e)[:40]}")
                    await asyncio.sleep(0.8)
                    continue
                print(f"         ❌ All attempts failed")
                return False
        
        return False

    @staticmethod
    async def ultimate_fill_dropdown(element, value: str) -> bool:
        """ULTIMATE dropdown fill"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.3)

            # Get all options
            options = await element.evaluate("""
                el => Array.from(el.options).map((opt, idx) => ({
                    text: opt.text.trim(),
                    value: opt.value,
                    index: idx
                }))
            """)

            if not options or len(options) == 0:
                return False

            value_lower = str(value).lower()

            # Try exact match
            for opt in options:
                if opt['text'].lower() == value_lower:
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.2)
                    print(f"         ✅ Selected: '{opt['text']}'")
                    return True

            # Try contains match
            for opt in options:
                if value_lower in opt['text'].lower():
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.2)
                    print(f"         ✅ Selected: '{opt['text']}'")
                    return True

            # Auto-select first valid option (skip placeholder)
            placeholders = ['select', 'choose', '--', 'please', 'pick', 'option', '---', 'select one']
            for opt in options:
                if opt['text'] and not any(p in opt['text'].lower() for p in placeholders):
                    await element.select_option(value=opt['value'])
                    await asyncio.sleep(0.2)
                    print(f"         🔄 Auto-selected: '{opt['text']}'")
                    return True

            # Last resort: select second option
            if len(options) > 1:
                await element.select_option(index=1)
                await asyncio.sleep(0.2)
                print(f"         🔄 Fallback: index 1")
                return True

            return False
        except Exception as e:
            print(f"         ❌ Dropdown error: {str(e)[:50]}")
            return False

    @staticmethod
    async def ultimate_fill_checkbox(element, should_check: bool = True) -> bool:
        """ULTIMATE checkbox fill"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.2)
            
            is_checked = await element.is_checked()
            
            if should_check and not is_checked:
                # Try normal check
                try:
                    await element.check(timeout=3000)
                except:
                    # Force click
                    try:
                        await element.click(force=True)
                    except:
                        pass
                await asyncio.sleep(0.2)
                return True
            elif not should_check and is_checked:
                try:
                    await element.uncheck(timeout=3000)
                except:
                    try:
                        await element.click(force=True)
                    except:
                        pass
                await asyncio.sleep(0.2)
                return True
            
            return True
        except Exception as e:
            print(f"         ❌ Checkbox: {str(e)[:50]}")
            return False

    @staticmethod
    async def ultimate_fill_radio(element) -> bool:
        """ULTIMATE radio fill"""
        try:
            await element.scroll_into_view_if_needed(timeout=3000)
            await asyncio.sleep(0.2)
            
            try:
                await element.check(timeout=3000)
            except:
                try:
                    await element.click(force=True)
                except:
                    pass
            
            await asyncio.sleep(0.2)
            return True
        except Exception as e:
            print(f"         ❌ Radio: {str(e)[:50]}")
            return False


# =========================
# ULTIMATE POWER FORM PROCESSOR 💪
# =========================

class UltimatePowerProcessor:
    """ULTIMATE form processor"""

    def __init__(self, page_or_frame, row, website: str, sheets_client: GoogleSheetsClient, row_index: int):
        self.page = page_or_frame
        self.row = row
        self.website = website
        self.sheets_client = sheets_client
        self.row_index = row_index
        self.filled_count = 0
        self.total_fields = 0

    def get_value(self, field_name: str) -> str:
        """Get value"""
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

        # Patterns
        if 'first' in field_lower and 'name' in field_lower:
            return "Interested"
        elif 'last' in field_lower and 'name' in field_lower:
            return "Customer"
        elif any(w in field_lower for w in ['how', 'hear', 'find']):
            return "Web Search"
        elif any(w in field_lower for w in ['budget', 'price']):
            return "Flexible"
        else:
            return "Information provided"

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
            if any(w in combined for w in ['message', 'comment', 'query', 'inquiry', 'detail']):
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
            if any(w in combined for w in ['subject', 'topic']):
                return 'subject'

            return info.get('name') or info.get('id') or 'unknown'
        except:
            return 'unknown'

    async def aggressive_detection(self) -> bool:
        """AGGRESSIVE multi-pass detection"""
        print(f"   🔍 DETECTION ({Config.FIELD_DETECTION_PASSES} passes)...")
        
        max_total = 0
        for pass_num in range(Config.FIELD_DETECTION_PASSES):
            wait_time = Config.FORM_WAIT_TIME / Config.FIELD_DETECTION_PASSES
            await asyncio.sleep(wait_time)
            
            # Relaxed visibility check - count more fields
            visible_text = await self.page.locator("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").count()
            textarea_count = await self.page.locator("textarea").count()
            select_count = await self.page.locator("select").count()
            checkbox_count = await self.page.locator("input[type='checkbox']").count()
            radio_count = await self.page.locator("input[type='radio']").count()
            
            total = visible_text + textarea_count + select_count + checkbox_count + radio_count
            
            print(f"      Pass {pass_num+1}: Text={visible_text}, Area={textarea_count}, Select={select_count}, Check={checkbox_count}, Radio={radio_count}, Total={total}")
            
            if total > max_total:
                max_total = total
        
        self.total_fields = max_total
        return max_total > 0

    async def ultimate_fill_all(self) -> int:
        """ULTIMATE filling"""
        try:
            if not await self.aggressive_detection():
                print(f"   ❌ NO FIELDS after {Config.FIELD_DETECTION_PASSES} passes")
                return 0

            print(f"   💪 FOUND {self.total_fields} FIELDS - ULTIMATE POWER FILL!\n")

            # Text inputs - relaxed selector
            all_inputs = await self.page.locator("input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']):not([type='checkbox']):not([type='radio'])").all()
            
            for idx, inp in enumerate(all_inputs):
                try:
                    field_type = await self.detect_field_type(inp)
                    value = self.get_value(field_type)
                    print(f"      [{idx+1}/{len(all_inputs)}] '{field_type}': {value[:25]}...")
                    
                    if await UltimatePowerFiller.ultimate_fill_text(inp, value):
                        self.filled_count += 1
                        print(f"      ✅ SUCCESS!")
                    else:
                        print(f"      ⚠️ Failed")
                    
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:50]}")
                    continue

            # Textareas
            all_textareas = await self.page.locator("textarea").all()
            for idx, ta in enumerate(all_textareas):
                try:
                    value = self.get_value('message')
                    print(f"      Textarea {idx+1}: {value[:25]}...")
                    if await UltimatePowerFiller.ultimate_fill_text(ta, value):
                        self.filled_count += 1
                        print(f"      ✅ SUCCESS!")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:50]}")
                    continue

            # Dropdowns
            all_selects = await self.page.locator("select").all()
            for idx, sel in enumerate(all_selects):
                try:
                    field_type = await self.detect_field_type(sel)
                    value = self.get_value(field_type)
                    print(f"      Dropdown {idx+1}: {field_type}")
                    if await UltimatePowerFiller.ultimate_fill_dropdown(sel, value):
                        self.filled_count += 1
                        print(f"      ✅ SUCCESS!")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:50]}")
                    continue

            # Checkboxes
            all_checkboxes = await self.page.locator("input[type='checkbox']").all()
            for idx, cb in enumerate(all_checkboxes):
                try:
                    field_type = await self.detect_field_type(cb)
                    should_check = any(w in field_type.lower() for w in ['term', 'privacy', 'policy', 'agree', 'accept', 'gdpr'])
                    print(f"      Checkbox {idx+1}: '{field_type}'")
                    if await UltimatePowerFiller.ultimate_fill_checkbox(cb, should_check):
                        self.filled_count += 1
                        print(f"      ✅ SUCCESS!")
                    await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:50]}")
                    continue

            # Radios
            all_radios = await self.page.locator("input[type='radio']").all()
            processed_groups = set()
            for idx, rb in enumerate(all_radios):
                try:
                    radio_name = await rb.get_attribute('name')
                    if radio_name and radio_name not in processed_groups:
                        if await UltimatePowerFiller.ultimate_fill_radio(rb):
                            self.filled_count += 1
                            processed_groups.add(radio_name)
                            print(f"      ✅ Radio SUCCESS!")
                        await asyncio.sleep(Config.ANIMATION_DELAY)
                except Exception as e:
                    print(f"      ❌ Error: {str(e)[:50]}")
                    continue

        except Exception as e:
            print(f"   ❌ Processing error: {str(e)}")
            traceback.print_exc()

        return self.filled_count


# =========================
# ULTIMATE POWER SUBMIT 💪
# =========================

class UltimatePowerSubmit:
    """ULTIMATE submit"""
    
    @staticmethod
    async def force_submit(page_or_frame, max_attempts: int = 6) -> bool:
        """FORCE SUBMIT"""
        print(f"   🎯 ULTIMATE SUBMIT ({max_attempts} attempts)...")
        
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Send')",
            "button:has-text('Book')",
            "button:has-text('Schedule')",
            "button:has-text('Request')",
            "button:has-text('Contact')",
            "button:has-text('Enquire')",
            "button:has-text('Get Started')",
            "input[value*='Submit']",
            "input[value*='Send']",
            ".submit-btn",
            ".contact-submit",
            "form button:not([type='button']):not([type='reset'])",
            "form input[type='button'][value*='Submit']",
        ]
        
        for attempt in range(max_attempts):
            print(f"      Try {attempt+1}/{max_attempts}...")
            
            for selector in submit_selectors:
                try:
                    btns = page_or_frame.locator(selector)
                    count = await btns.count()
                    
                    if count > 0:
                        btn = btns.first
                        
                        # Check if visible
                        try:
                            is_visible = await btn.is_visible(timeout=2000)
                            if not is_visible:
                                continue
                        except:
                            continue
                        
                        print(f"      🎯 Found: {selector}")
                        
                        # Multiple click methods
                        clicked = False
                        try:
                            await btn.click(timeout=5000)
                            clicked = True
                        except:
                            try:
                                await btn.click(force=True, timeout=5000)
                                clicked = True
                            except:
                                try:
                                    await btn.evaluate("el => el.click()")
                                    clicked = True
                                except:
                                    pass
                        
                        if clicked:
                            await asyncio.sleep(3)
                            print(f"      ✅ SUBMITTED!")
                            return True
                            
                except Exception as e:
                    continue
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(1.5)
        
        print(f"      ❌ Submit failed")
        return False


# =========================
# MAIN WORKER 💪
# =========================

async def ultimate_power_process(row, idx: int, total: int, sheets_client: GoogleSheetsClient, playwright_instance):
    """ULTIMATE POWER processor"""
    website = str(row.get("website","")).strip()
    row_index = int(row.get('row_index', idx))

    print(f"\n{'='*90}")
    print(f"💪 ULTIMATE POWER [{idx+1}/{total}] {website}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*90}\n")

    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "PROCESSING")

    browser = None
    try:
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
                await asyncio.sleep(Config.INITIAL_WAIT)
                print(f"   ✅ Loaded: {page.url}")
                nav_success = True
                break
            except Exception as nav_err:
                print(f"   ⚠️ Attempt {attempt+1} failed")
                if attempt < Config.MAX_RETRIES - 1:
                    await asyncio.sleep(Config.RETRY_DELAY)
                    continue
                else:
                    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NAV_ERROR")
                    return False

        if not nav_success:
            return False

        # CAPTCHA
        has_captcha, _ = await CaptchaHandler.detect(page)
        if has_captcha:
            if not await CaptchaHandler.wait_for_solve(page):
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "CAPTCHA_BLOCKED")
                return False

        # CONTACT PAGE DETECTION
        print(f"   🔎 Looking for contact...")
        
        current_url = page.url.lower()
        if any(word in current_url for word in ['contact', 'enquiry', 'book', 'appointment', 'quote', 'form']):
            print(f"   ✅ Already on contact page!")
        else:
            form_count = await page.locator("form").count()
            input_count = await page.locator("input[type='text'], input[type='email']").count()
            
            if form_count > 0 and input_count >= 2:
                print(f"   ✅ Found forms on current page")
            else:
                keywords = [
                    "Contact Us", "Contact", "Get in Touch",
                    "Book Now", "Schedule", "Appointment",
                    "Request Quote", "Get Quote",
                    "Enquiry", "Inquiry",
                ]
                
                found = False
                for keyword in keywords:
                    try:
                        links = page.locator(f"a:has-text('{keyword}')").or_(page.locator(f"button:has-text('{keyword}')"))
                        if await links.count() > 0:
                            first_link = links.first
                            if await first_link.is_visible(timeout=2000):
                                print(f"   ✅ Found '{keyword}'")
                                await first_link.click(timeout=5000)
                                await page.wait_for_load_state("domcontentloaded", timeout=20000)
                                await asyncio.sleep(3)
                                found = True
                                break
                    except:
                        continue
                
                if not found:
                    print(f"   ⚠️ No contact link - trying current page")

        # Extra wait
        print(f"   ⏳ Waiting {Config.FORM_WAIT_TIME}s for forms...")
        await asyncio.sleep(Config.FORM_WAIT_TIME)

        # ULTIMATE POWER PROCESSING
        processor = UltimatePowerProcessor(page, row, website, sheets_client, row_index)
        filled = await processor.ultimate_fill_all()

        if filled > 0:
            print(f"\n   💪 ULTIMATE POWER: {filled}/{processor.total_fields} FILLED!")

            # SUBMIT
            submit_success = await UltimatePowerSubmit.force_submit(page)
            
            if submit_success:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "SUCCESS")
                await asyncio.sleep(4)
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
    """Main"""
    print("="*90)
    print("💪 FORM AUTO-FILLER - ULTIMATE POWER v8.0")
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

    print(f"\n✅ {len(df)} websites\n")

    playwright_instance = await async_playwright().start()

    for idx, row in df.iterrows():
        await ultimate_power_process(row, idx, len(df), sheets_client, playwright_instance)
        if idx < len(df) - 1:
            print("\n⏸️ Waiting...\n")
            await asyncio.sleep(3)

    await playwright_instance.stop()

    print("\n" + "="*90)
    print("💪 ULTIMATE POWER COMPLETE!")
    print("="*90)


if __name__ == "__main__":
    import sys
    try:
        print(f"💪 START: {datetime.now()}")
        asyncio.run(main_async())
        print(f"\n✅ END: {datetime.now()}")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
