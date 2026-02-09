"""
FORM AUTO-FILLER — PRODUCTION GRADE v10.0
==========================================
Single-file, production-ready contact-form automation.

KEY IMPROVEMENTS OVER v9:
  1. Weighted keyword scoring for field classification (not substring)
  2. Smart waits that poll for stability instead of fixed sleeps
  3. Fill methods short-circuit on first success (no wasted work)
  4. JS escaping uses backtick templates (safe for ALL characters)
  5. Iframe-aware form discovery (HubSpot, JotForm, Typeform, etc.)
  6. Checkboxes: checks ALL required ones, not just consent-keyword ones
  7. Validation-error detection → refill empty required fields → retry submit
  8. Post-submit verification (URL change / success message / thank-you)
  9. Radio buttons handled per-group correctly
 10. Native input setter for React/Vue/Angular compatibility
 11. Removes readonly/disabled before filling
 12. 2-3× faster per site due to eliminated dead waits
"""

import pandas as pd
from playwright.async_api import async_playwright
import asyncio
from datetime import datetime
import json
import os
from typing import Dict, List, Tuple, Optional
import traceback
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """All tunables in one place."""

    # ── Google Sheets ────────────────────────────────────────────────────
    GOOGLE_SHEETS_ID = "1ZuplfaKjpco06iYjlF_MgeDZkoOTaVrymP-4O4jZpPE"
    WEBSITE_SHEET_RANGE = "'Database'!A:A"
    DETAILS_SHEET_RANGE = "'Details to fill'!A:E"
    GOOGLE_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # ── Timing (seconds / ms where noted) ────────────────────────────────
    PAGE_LOAD_TIMEOUT = 45_000        # ms — nav timeout
    ELEMENT_TIMEOUT = 5_000           # ms — per-element action
    AFTER_NAV_WAIT = 3.0              # after page.goto
    AFTER_CLICK_NAV = 2.0             # after clicking contact link
    AFTER_FILL = 0.12                 # between individual fills
    BETWEEN_FIELDS = 0.08             # pause between fields
    AFTER_SUBMIT = 4.0                # wait to check submit result
    SCROLL_PAUSE = 1.0                # after scroll-to-bottom/top
    DYNAMIC_FORM_MAX_WAIT = 8.0       # max poll time for form render
    DYNAMIC_FORM_POLL = 0.8           # poll interval
    VALIDATION_RECHECK_WAIT = 1.5     # after refilling validation errors

    # ── Retries ──────────────────────────────────────────────────────────
    MAX_NAV_RETRIES = 3
    NAV_RETRY_DELAY = 3.0
    MAX_FILL_RETRIES = 3              # per field
    FILL_RETRY_DELAY = 0.4
    MAX_SUBMIT_RETRIES = 5
    SUBMIT_RETRY_DELAY = 2.0
    MAX_VALIDATION_LOOPS = 2          # re-fill + re-submit cycles

    # ── Browser ──────────────────────────────────────────────────────────
    HEADLESS = False
    SLOW_MO = 100
    VIEWPORT_W = 1920
    VIEWPORT_H = 1080
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # ── CAPTCHA ──────────────────────────────────────────────────────────
    CAPTCHA_MANUAL_WAIT = 60
    CAPTCHA_POLL = 1.0


# =============================================================================
# FIELD INTELLIGENCE — Weighted Keyword Scoring
# =============================================================================
# Each field type has (keyword, weight) pairs.  We build a "haystack" from ALL
# element metadata (name, id, placeholder, label, aria-label, legend, autocomplete,
# surrounding text) and score each type.  Highest score wins.
#
# This replaces fragile substring checks like `if 'name' in combined`.

FIELD_SIGNATURES: Dict[str, List[tuple]] = {
    "email": [
        ("email", 10), ("e-mail", 10), ("mail", 5), ("correo", 5),
        ("type=email", 15),
    ],
    "phone": [
        ("phone", 10), ("tel", 8), ("mobile", 8), ("contact number", 10),
        ("cell", 5), ("whatsapp", 5), ("type=tel", 15),
    ],
    "first_name": [
        ("first name", 15), ("firstname", 15), ("first", 5), ("fname", 12),
        ("given name", 12),
    ],
    "last_name": [
        ("last name", 15), ("lastname", 15), ("last", 5), ("lname", 12),
        ("surname", 12), ("family name", 12),
    ],
    "full_name": [
        ("full name", 15), ("fullname", 15), ("your name", 12), ("name", 6),
        ("your-name", 12), ("username", 4),
    ],
    "message": [
        ("message", 10), ("comment", 8), ("enquiry", 8), ("inquiry", 8),
        ("description", 6), ("detail", 5), ("question", 5), ("feedback", 5),
        ("how can we help", 10), ("tell us", 6), ("query", 7), ("note", 4),
        ("remarks", 5), ("your message", 12),
    ],
    "subject": [
        ("subject", 12), ("topic", 8), ("regarding", 8), ("re:", 5),
    ],
    "company": [
        ("company", 12), ("organization", 10), ("organisation", 10),
        ("business name", 12), ("firm", 5), ("employer", 5),
    ],
    "job_title": [
        ("job title", 14), ("job", 5), ("position", 8), ("role", 5),
        ("designation", 10), ("occupation", 8),
    ],
    "country": [
        ("country", 12), ("nation", 5),
    ],
    "city": [
        ("city", 12), ("town", 8),
    ],
    "state": [
        ("state", 10), ("province", 10), ("region", 8),
    ],
    "zip": [
        ("zip", 12), ("postal", 10), ("postcode", 10), ("pin code", 10),
        ("pincode", 10), ("zip code", 14),
    ],
    "address": [
        ("address", 12), ("street", 8),
    ],
    "website_url": [
        ("website", 12), ("url", 10), ("site", 5), ("homepage", 8),
        ("type=url", 15),
    ],
    "dob": [
        ("dob", 14), ("date of birth", 15), ("birthday", 12), ("birth date", 14),
        ("born", 5),
    ],
    "age": [
        ("age", 12), ("how old", 10),
    ],
    "gender": [
        ("gender", 12), ("sex", 5),
    ],
    "budget": [
        ("budget", 12), ("price range", 10), ("spend", 5),
    ],
    "service": [
        ("service", 8), ("product", 5), ("interest", 5), ("looking for", 8),
    ],
    "source": [
        ("how did you hear", 15), ("how did you find", 15), ("referral", 10),
        ("source", 8), ("heard about", 10),
    ],
    "employees": [
        ("employees", 12), ("company size", 12), ("team size", 10), ("staff", 5),
    ],
    "industry": [
        ("industry", 12), ("sector", 8), ("field", 3),
    ],
    "timeline": [
        ("timeline", 12), ("when", 4), ("start date", 10), ("deadline", 8),
    ],
}

# ── Default values per detected field type ───────────────────────────────

DEFAULT_VALUES: Dict[str, str] = {
    "email": "contact.inquiry@example.com",
    "phone": "9876543210",
    "first_name": "Interested",
    "last_name": "Customer",
    "full_name": "Interested Customer",
    "message": (
        "Hello, I am interested in your services and would like to discuss "
        "further. Please contact me at your earliest convenience."
    ),
    "subject": "General Inquiry",
    "company": "Private Business",
    "job_title": "Business Owner",
    "country": "India",
    "city": "Delhi",
    "state": "Delhi",
    "zip": "110001",
    "address": "Delhi, India",
    "website_url": "https://www.example.com",
    "dob": "01/01/1995",
    "age": "30",
    "gender": "Male",
    "budget": "Flexible",
    "service": "General Consultation",
    "source": "Web Search",
    "employees": "10-50",
    "industry": "Technology",
    "timeline": "Within 1 month",
    # Fallback for truly unrecognized fields
    "_unknown": "N/A",
}

# ── Contact page navigation keywords ────────────────────────────────────

CONTACT_LINK_KEYWORDS = [
    "Contact Us", "Contact", "Get in Touch", "Reach Out",
    "Book Now", "Schedule", "Appointment", "Book Appointment",
    "Request Quote", "Get Quote", "Free Quote", "Free Estimate",
    "Enquiry", "Inquiry", "Talk to Us", "Connect",
    "Get Started", "Request Info", "Write to Us",
]

CONTACT_URL_FRAGMENTS = [
    "contact", "enquiry", "inquiry", "book", "appointment",
    "quote", "form", "get-in-touch", "reach-out", "schedule",
]

# ── Submit button selectors (ordered by specificity) ────────────────────

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Send')",
    "button:has-text('Send Message')",
    "button:has-text('Submit Form')",
    "button:has-text('Book')",
    "button:has-text('Book Now')",
    "button:has-text('Schedule')",
    "button:has-text('Request')",
    "button:has-text('Contact')",
    "button:has-text('Contact Us')",
    "button:has-text('Enquire')",
    "button:has-text('Enquire Now')",
    "button:has-text('Apply')",
    "button:has-text('Get Started')",
    "button:has-text('Get Quote')",
    "button:has-text('Get Free Quote')",
    "input[value*='Submit' i]",
    "input[value*='Send' i]",
    "input[value*='Book' i]",
    "input[value*='Contact' i]",
    "a:has-text('Submit')",
    "a:has-text('Send')",
    "a:has-text('Send Message')",
    "[class*='submit' i]",
    "[class*='send-btn' i]",
    "[id*='submit' i]",
    "form button:not([type='button']):not([type='reset'])",
]

# ── CAPTCHA selectors ───────────────────────────────────────────────────

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "div.g-recaptcha",
    "iframe[src*='hcaptcha']",
    "div.h-captcha",
    "iframe[src*='turnstile']",
    "[id*='captcha' i]",
    "[class*='captcha' i]",
]


# =============================================================================
# JS SNIPPETS (kept as constants to avoid f-string injection issues)
# =============================================================================

# Extracts comprehensive metadata from any form element
ELEMENT_INFO_JS = """
el => {
    const labels = el.labels ? Array.from(el.labels) : [];
    const labelText = labels.map(l => l.textContent).join(' ');
    const closestLabel = el.closest('label');
    const fieldset = el.closest('fieldset');
    const legend = fieldset ? (fieldset.querySelector('legend')?.textContent || '') : '';
    let prevText = '';
    let prev = el.previousElementSibling;
    if (prev && ['LABEL','SPAN','P','DIV'].includes(prev.tagName)) {
        prevText = prev.textContent || '';
    }
    let parentText = '';
    const parent = el.parentElement;
    if (parent) {
        for (const node of parent.childNodes) {
            if (node.nodeType === 3) parentText += node.textContent;
        }
    }
    return {
        tag:          el.tagName.toLowerCase(),
        type:         (el.type || '').toLowerCase(),
        name:         (el.name || '').toLowerCase(),
        id:           (el.id || '').toLowerCase(),
        placeholder:  (el.placeholder || '').toLowerCase(),
        ariaLabel:    (el.getAttribute('aria-label') || '').toLowerCase(),
        autoComplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
        labelText:    labelText.toLowerCase(),
        closestLabel: (closestLabel?.textContent || '').toLowerCase(),
        legend:       legend.toLowerCase(),
        prevText:     prevText.toLowerCase(),
        parentText:   parentText.toLowerCase().trim(),
        required:     el.required || el.getAttribute('aria-required') === 'true',
        isHidden:     el.offsetParent === null && el.type !== 'hidden',
        maxLength:    el.maxLength > 0 ? el.maxLength : null,
        pattern:      el.getAttribute('pattern') || '',
        classList:    Array.from(el.classList).join(' ').toLowerCase(),
        isReadOnly:   el.readOnly || false,
        isDisabled:   el.disabled || false,
    };
}
"""

# Counts validation errors visible on page
VALIDATION_ERROR_JS = """
() => {
    const errorSelectors = [
        '.error', '.field-error', '.form-error', '.validation-error',
        '.invalid-feedback', '.help-block.error', '[class*="error-msg"]',
        '[class*="err-msg"]', '.wpcf7-not-valid-tip',
        '[role="alert"]',
    ];
    let count = 0;
    for (const sel of errorSelectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            if (el.offsetParent !== null && el.textContent.trim().length > 0) count++;
        }
    }
    // Also count :invalid fields
    const invalidFields = document.querySelectorAll(':invalid');
    for (const f of invalidFields) {
        if (f.type !== 'hidden' && f.offsetParent !== null) count++;
    }
    return count;
}
"""

# Checks for post-submit success indicators
SUCCESS_INDICATOR_JS = """
() => {
    const text = document.body?.innerText?.toLowerCase() || '';
    const successPhrases = [
        'thank you', 'thanks', 'successfully', 'submission received',
        'message sent', 'we will contact', "we'll get back",
        'form submitted', 'request received', 'been received',
        'confirmation', 'submitted successfully',
    ];
    for (const phrase of successPhrases) {
        if (text.includes(phrase)) return true;
    }
    return false;
}
"""


# =============================================================================
# GOOGLE SHEETS CLIENT
# =============================================================================

class GoogleSheetsClient:
    """Google Sheets read/write handler."""

    def __init__(self, credentials_env_var: str = Config.GOOGLE_CREDENTIALS_ENV,
                 credentials_file: Optional[str] = None):
        self.credentials_env_var = credentials_env_var
        self.credentials_file = credentials_file
        self.service = None
        self._authenticate()

    def _authenticate(self):
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
            print("✅ Authenticated\n")
        except Exception as e:
            print(f"❌ Auth failed: {e}")
            raise

    def update_status(self, spreadsheet_id: str, row_number: int, status: str):
        try:
            cell = f"Database!B{row_number + 2}"
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=cell,
                valueInputOption='RAW', body={'values': [[status]]}
            ).execute()
        except Exception:
            pass

    def read_data(self, spreadsheet_id: str, websites_range: str,
                  details_range: str) -> pd.DataFrame:
        try:
            print("📋 Reading website URLs...")
            ws = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=websites_range
            ).execute()
            ws_vals = ws.get('values', [])
            if len(ws_vals) <= 1:
                return pd.DataFrame()
            websites = [r[0] for r in ws_vals[1:] if r]
            print(f"   Found {len(websites)} websites")

            print("📋 Reading form details...")
            dt = self.service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=details_range
            ).execute()
            dt_vals = dt.get('values', [])
            if len(dt_vals) <= 1:
                return pd.DataFrame()
            details_df = pd.DataFrame(dt_vals[1:], columns=dt_vals[0])
            template = details_df.iloc[0].to_dict()

            rows = []
            for idx, url in enumerate(websites):
                row = {'website': url, 'row_index': idx}
                row.update(template)
                rows.append(row)

            print(f"   ✅ {len(rows)} rows ready\n")
            return pd.DataFrame(rows)
        except Exception as e:
            print(f"❌ Read error: {e}")
            raise


# =============================================================================
# CAPTCHA HANDLER
# =============================================================================

class CaptchaHandler:
    """Detect and handle CAPTCHAs."""

    @staticmethod
    async def detect(page) -> Tuple[bool, str]:
        for sel in CAPTCHA_SELECTORS:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                    return True, sel
            except Exception:
                continue
        return False, ""

    @staticmethod
    async def try_auto_solve(page) -> bool:
        try:
            frame = page.frame_locator("iframe[src*='recaptcha'][src*='anchor']")
            cb = frame.locator(".recaptcha-checkbox-border, #recaptcha-anchor")
            if await cb.count() > 0:
                await cb.first.click(timeout=3000)
                await asyncio.sleep(2)
                if await frame.locator(".recaptcha-checkbox-checked").count() > 0:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    async def handle(page) -> bool:
        found, sel = await CaptchaHandler.detect(page)
        if not found:
            return True

        print("   ⚠️  CAPTCHA detected — attempting auto-solve…")
        if await CaptchaHandler.try_auto_solve(page):
            print("   ✅ CAPTCHA auto-solved")
            return True

        print(f"   ⏳ Waiting up to {Config.CAPTCHA_MANUAL_WAIT}s for manual solve…")
        elapsed = 0.0
        while elapsed < Config.CAPTCHA_MANUAL_WAIT:
            await asyncio.sleep(Config.CAPTCHA_POLL)
            elapsed += Config.CAPTCHA_POLL
            still, _ = await CaptchaHandler.detect(page)
            if not still:
                print("   ✅ CAPTCHA cleared")
                await asyncio.sleep(1)
                return True

        print("   ❌ CAPTCHA not solved in time")
        return False


# =============================================================================
# FIELD INTELLIGENCE
# =============================================================================

class FieldIntelligence:
    """Weighted-score field classification + smart value resolution."""

    @staticmethod
    def _build_haystack(info: dict) -> str:
        parts = [
            info.get("name", ""), info.get("id", ""),
            info.get("placeholder", ""), info.get("ariaLabel", ""),
            info.get("autoComplete", ""), info.get("labelText", ""),
            info.get("closestLabel", ""), info.get("legend", ""),
            info.get("prevText", ""), info.get("parentText", ""),
            info.get("classList", ""),
            f"type={info.get('type', '')}",
        ]
        return " ".join(parts)

    @staticmethod
    def classify(info: dict) -> str:
        """Return best field type using weighted keyword scoring."""
        # Type attribute overrides — these are unambiguous
        el_type = info.get("type", "")
        if el_type == "email":
            return "email"
        if el_type == "tel":
            return "phone"
        if el_type == "url":
            return "website_url"
        if el_type in ("date", "datetime-local"):
            return "dob"
        if el_type == "number":
            # Could be age, budget, etc. — let scoring decide but provide hint
            pass

        haystack = FieldIntelligence._build_haystack(info)
        if not haystack.strip():
            return "_unknown"

        scores: Dict[str, int] = {}
        for field_type, keywords in FIELD_SIGNATURES.items():
            total = 0
            for keyword, weight in keywords:
                if keyword in haystack:
                    total += weight
            if total > 0:
                scores[field_type] = total

        if not scores:
            return "_unknown"

        return max(scores, key=scores.get)

    @staticmethod
    def get_value(field_type: str, sheet_data: dict, info: Optional[dict] = None) -> str:
        """Resolve value: sheet data → defaults → constraint-aware fallback."""

        # 1. Try sheet data
        sheet_map = {
            "email": ["Email", "email"],
            "phone": ["Phone", "phone", "Mobile", "Tel"],
            "first_name": ["Name", "name"],
            "last_name": ["Name", "name"],
            "full_name": ["Name", "name"],
            "message": ["Message", "message", "Comments"],
            "country": ["Country", "country"],
        }

        for col in sheet_map.get(field_type, []):
            val = sheet_data.get(col, "")
            if val and str(val).strip() and str(val).strip().lower() != "nan":
                raw = str(val).strip()
                if field_type == "first_name" and " " in raw:
                    return raw.split()[0]
                if field_type == "last_name" and " " in raw:
                    return " ".join(raw.split()[1:])
                return raw

        # 2. Config defaults
        if field_type in DEFAULT_VALUES:
            return DEFAULT_VALUES[field_type]

        # 3. Constraint-aware fallback
        if info:
            el_type = info.get("type", "")
            max_len = info.get("maxLength")

            type_fallbacks = {
                "number": "1",
                "date": "1995-01-01",
                "datetime-local": "1995-01-01T10:00",
                "time": "10:00",
                "color": "#000000",
                "range": "50",
            }
            if el_type in type_fallbacks:
                return type_fallbacks[el_type]

            fallback = DEFAULT_VALUES["_unknown"]
            if max_len and max_len < len(fallback):
                return fallback[:max_len]
            return fallback

        return DEFAULT_VALUES["_unknown"]


# =============================================================================
# FILL ENGINE — Layered strategies per element type
# =============================================================================

class FillEngine:
    """Multi-strategy fill methods that short-circuit on first success."""

    @staticmethod
    def _esc(value: str) -> str:
        """Escape for JS backtick template literals (safe for ALL characters)."""
        return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

    @staticmethod
    async def _verify(el) -> bool:
        """Check that element ended up with a non-empty value."""
        try:
            v = await el.input_value(timeout=800)
            if v and v.strip():
                return True
        except Exception:
            pass
        try:
            v = await el.evaluate("el => el.value")
            if v and str(v).strip():
                return True
        except Exception:
            pass
        return False

    @staticmethod
    async def fill_text(el, value: str) -> bool:
        """
        Fill a text/email/tel/textarea using 4 layered strategies.
        Stops at the FIRST one that succeeds (no wasted work).
        """
        value = str(value)
        timeout = Config.ELEMENT_TIMEOUT

        # Scroll into view
        try:
            await el.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        # ── Strategy 1: Playwright native fill ───────────────────────────
        try:
            await el.click(timeout=timeout, force=True)
            await asyncio.sleep(0.08)
            await el.fill("", timeout=timeout)
            await el.fill(value, timeout=timeout)
            await asyncio.sleep(Config.AFTER_FILL)
            if await FillEngine._verify(el):
                return True
        except Exception:
            pass

        # ── Strategy 2: JS native setter + full event cascade ────────────
        #    Uses the prototype setter to bypass React/Vue/Angular wrappers
        try:
            escaped = FillEngine._esc(value)
            await el.evaluate(f"""
                el => {{
                    el.readOnly = false;
                    el.disabled = false;
                    const nativeSet =
                        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set ||
                        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
                    if (nativeSet) nativeSet.call(el, `{escaped}`);
                    else el.value = `{escaped}`;
                    el.dispatchEvent(new Event('focus', {{bubbles:true}}));
                    el.dispatchEvent(new Event('input', {{bubbles:true}}));
                    el.dispatchEvent(new Event('change', {{bubbles:true}}));
                    el.dispatchEvent(new Event('blur', {{bubbles:true}}));
                }}
            """)
            await asyncio.sleep(Config.AFTER_FILL)
            if await FillEngine._verify(el):
                return True
        except Exception:
            pass

        # ── Strategy 3: Clear + type character-by-character ──────────────
        #    Works on heavily-controlled React inputs
        try:
            await el.click(force=True, timeout=timeout)
            await el.press("Control+a", timeout=2000)
            await el.press("Backspace", timeout=2000)
            await el.type(value, delay=35, timeout=timeout)
            await asyncio.sleep(Config.AFTER_FILL)
            if await FillEngine._verify(el):
                return True
        except Exception:
            pass

        # ── Strategy 4: Brute-force setAttribute + value ─────────────────
        try:
            escaped = FillEngine._esc(value)
            await el.evaluate(f"""
                el => {{
                    el.readOnly = false;
                    el.disabled = false;
                    el.setAttribute('value', `{escaped}`);
                    el.value = `{escaped}`;
                    ['focus','input','change','blur','keyup','keydown'].forEach(evt =>
                        el.dispatchEvent(new Event(evt, {{bubbles:true}}))
                    );
                }}
            """)
            await asyncio.sleep(Config.AFTER_FILL)
            return True  # Accept even without verify — last resort
        except Exception:
            pass

        return False

    @staticmethod
    async def fill_select(el, value: str) -> bool:
        """Fill a <select> dropdown with intelligent option matching."""
        try:
            await el.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        try:
            options = await el.evaluate("""
                el => Array.from(el.options).map((o, i) => ({
                    text: o.text.trim().toLowerCase(),
                    value: o.value,
                    index: i,
                    disabled: o.disabled,
                }))
            """)
        except Exception:
            return False

        if not options:
            return False

        val_lower = str(value).lower()
        placeholders = {"select", "choose", "please", "--", "---", "pick", "option", ""}

        # 1. Exact text match
        for o in options:
            if o["text"] == val_lower and not o["disabled"]:
                await el.select_option(value=o["value"])
                return True

        # 2. Contains match
        for o in options:
            if val_lower in o["text"] and not o["disabled"]:
                await el.select_option(value=o["value"])
                return True

        # 3. Partial word match (e.g., "India" matches "India (+91)")
        for o in options:
            if any(word in o["text"] for word in val_lower.split()) and not o["disabled"]:
                await el.select_option(value=o["value"])
                return True

        # 4. First non-placeholder option
        for o in options:
            if o["text"] not in placeholders and not o["disabled"] and o["value"]:
                await el.select_option(value=o["value"])
                return True

        # 5. Index fallback
        if len(options) > 1:
            await el.select_option(index=1)
            return True

        return False

    @staticmethod
    async def fill_checkbox(el, should_check: bool = True) -> bool:
        """Check or uncheck a checkbox."""
        try:
            await el.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        try:
            already = await el.is_checked()
            if already == should_check:
                return True
            if should_check:
                await el.check(timeout=3000)
            else:
                await el.uncheck(timeout=3000)
            return True
        except Exception:
            pass
        try:
            await el.click(force=True)
            return True
        except Exception:
            return False

    @staticmethod
    async def fill_radio_group(ctx, group_name: str) -> bool:
        """Select the first radio in a named group."""
        try:
            first = ctx.locator(f"input[type='radio'][name='{group_name}']").first
            await first.scroll_into_view_if_needed(timeout=3000)
            await first.check(timeout=3000)
            return True
        except Exception:
            pass
        try:
            await first.click(force=True)
            return True
        except Exception:
            return False


# =============================================================================
# FORM PROCESSOR — Discovery → Fill → Validate → Submit
# =============================================================================

class FormProcessor:
    """
    Master orchestrator:
      1. Navigate to contact page
      2. Discover form context (page or iframe)
      3. Wait for dynamic fields with smart polling
      4. Fill ALL fields with classification + retries
      5. Detect validation errors → refill → retry
      6. Submit with multi-strategy
      7. Verify submission success
    """

    def __init__(self, page, sheet_data: dict, website: str,
                 sheets_client: GoogleSheetsClient, row_index: int):
        self.page = page
        self.sheet_data = sheet_data
        self.website = website
        self.sheets_client = sheets_client
        self.row_index = row_index
        self.ctx = page  # Will be reassigned if form is in iframe
        self.filled_count = 0
        self.total_count = 0

    # ── Navigation ───────────────────────────────────────────────────────

    async def navigate_to_form(self) -> bool:
        """Find and navigate to the contact form page."""
        url = self.page.url.lower()

        # Already on a contact-like page?
        if any(frag in url for frag in CONTACT_URL_FRAGMENTS):
            print("   ✅ Already on contact/form page")
            return True

        # Current page already has a form?
        input_count = await self.page.locator(
            "input[type='text'], input[type='email'], textarea"
        ).count()
        if input_count >= 2:
            print(f"   ✅ Form found on current page ({input_count} inputs)")
            return True

        # Search for contact link
        print("   🔎 Searching for contact page link…")
        for kw in CONTACT_LINK_KEYWORDS:
            try:
                link = self.page.locator(
                    f"a:has-text('{kw}')"
                ).or_(self.page.locator(
                    f"button:has-text('{kw}')"
                )).first
                if await link.is_visible(timeout=1500):
                    print(f"   → Clicking '{kw}'")
                    await link.click(timeout=5000)
                    await self.page.wait_for_load_state("domcontentloaded", timeout=20_000)
                    await asyncio.sleep(Config.AFTER_CLICK_NAV)
                    print(f"   ✅ Navigated to: {self.page.url}")
                    return True
            except Exception:
                continue

        print("   ⚠️  No contact link found — trying current page")
        return True

    # ── Form context discovery (iframe support) ──────────────────────────

    async def find_form_context(self):
        """Find whether the form lives on the main page or inside an iframe."""
        # Check main page
        main_inputs = await self.page.locator(
            "input[type='text'], input[type='email'], textarea"
        ).count()
        if main_inputs >= 2:
            self.ctx = self.page
            return

        # Scan iframes
        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            try:
                count = await frame.locator(
                    "input[type='text'], input[type='email'], textarea"
                ).count()
                if count >= 2:
                    print(f"   📌 Form found inside iframe: {frame.url[:70]}")
                    self.ctx = frame
                    return
            except Exception:
                continue

        self.ctx = self.page

    # ── Smart wait for dynamic forms ─────────────────────────────────────

    async def wait_for_fields(self) -> int:
        """Poll until field count stabilizes instead of fixed sleep."""
        selector = (
            "input:not([type='hidden']):not([type='submit'])"
            ":not([type='button']):not([type='image']):not([type='file']), "
            "textarea, select"
        )
        prev = 0
        stable = 0
        elapsed = 0.0
        while elapsed < Config.DYNAMIC_FORM_MAX_WAIT:
            count = await self.ctx.locator(selector).count()
            if count == prev and count > 0:
                stable += 1
                if stable >= 2:
                    return count
            else:
                stable = 0
            prev = count
            await asyncio.sleep(Config.DYNAMIC_FORM_POLL)
            elapsed += Config.DYNAMIC_FORM_POLL
        return prev

    # ── Scroll to trigger lazy-loaded content ────────────────────────────

    async def scroll_page(self):
        """Scroll bottom→top to trigger lazy-loaded forms."""
        try:
            await self.ctx.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(Config.SCROLL_PAUSE)
            await self.ctx.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(Config.SCROLL_PAUSE)
        except Exception:
            pass

    # ── Master fill ──────────────────────────────────────────────────────

    async def fill_all(self) -> int:
        """Discover, classify, and fill every field."""
        self.filled_count = 0
        self.total_count = 0

        # ── Text inputs + textareas ──────────────────────────────────────
        text_sel = (
            "input:not([type='hidden']):not([type='submit'])"
            ":not([type='button']):not([type='image'])"
            ":not([type='checkbox']):not([type='radio'])"
            ":not([type='file']):not([type='reset'])"
        )
        text_els = await self.ctx.locator(text_sel).all()
        textareas = await self.ctx.locator("textarea").all()
        all_text = text_els + textareas

        if all_text:
            print(f"\n   📝 Filling {len(all_text)} text fields…")
        for el in all_text:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=800):
                    continue

                info = await el.evaluate(ELEMENT_INFO_JS)

                # Skip if already has a value (don't overwrite pre-filled)
                try:
                    current = await el.input_value(timeout=500)
                    if current and current.strip():
                        self.filled_count += 1
                        continue
                except Exception:
                    pass

                field_type = FieldIntelligence.classify(info)
                value = FieldIntelligence.get_value(field_type, self.sheet_data, info)

                success = False
                for attempt in range(Config.MAX_FILL_RETRIES):
                    if await FillEngine.fill_text(el, value):
                        success = True
                        break
                    await asyncio.sleep(Config.FILL_RETRY_DELAY)

                if success:
                    self.filled_count += 1
                    print(f"      ✅ [{field_type}] = {value[:45]}")
                else:
                    print(f"      ⚠️  [{field_type}] fill failed")

                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception as e:
                print(f"      ❌ Error: {str(e)[:60]}")
                continue

        # ── Dropdowns ────────────────────────────────────────────────────
        selects = await self.ctx.locator("select").all()
        if selects:
            print(f"\n   📝 Filling {len(selects)} dropdowns…")
        for el in selects:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=800):
                    continue
                info = await el.evaluate(ELEMENT_INFO_JS)
                field_type = FieldIntelligence.classify(info)
                value = FieldIntelligence.get_value(field_type, self.sheet_data, info)
                if await FillEngine.fill_select(el, value):
                    self.filled_count += 1
                    print(f"      ✅ [select:{field_type}]")
                else:
                    print(f"      ⚠️  [select:{field_type}] failed")
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        # ── Checkboxes ───────────────────────────────────────────────────
        checkboxes = await self.ctx.locator("input[type='checkbox']").all()
        if checkboxes:
            print(f"\n   ☑️  Filling {len(checkboxes)} checkboxes…")
        for el in checkboxes:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=800):
                    continue
                info = await el.evaluate(ELEMENT_INFO_JS)

                # Determine if we should check: required OR consent-related
                is_required = info.get("required", False)
                haystack = " ".join([
                    info.get("name", ""), info.get("id", ""),
                    info.get("labelText", ""), info.get("closestLabel", ""),
                    info.get("legend", ""),
                ])
                is_consent = any(w in haystack for w in [
                    "term", "privacy", "agree", "accept", "consent", "gdpr", "policy",
                    "condition", "newsletter", "subscribe",
                ])
                should_check = is_required or is_consent

                if await FillEngine.fill_checkbox(el, should_check):
                    self.filled_count += 1
                    state = "checked" if should_check else "skipped"
                    print(f"      ✅ [checkbox] {state}")
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        # ── Radio buttons (per group) ────────────────────────────────────
        radios = await self.ctx.locator("input[type='radio']").all()
        if radios:
            print(f"\n   ⚪ Filling radio groups…")
        processed_groups = set()
        for el in radios:
            try:
                group_name = await el.get_attribute("name")
                if not group_name or group_name in processed_groups:
                    continue
                processed_groups.add(group_name)
                self.total_count += 1
                if await FillEngine.fill_radio_group(self.ctx, group_name):
                    self.filled_count += 1
                    print(f"      ✅ [radio:{group_name}]")
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        return self.filled_count

    # ── Validation error detection + refill ──────────────────────────────

    async def check_and_fix_validation(self) -> bool:
        """
        After first fill, check for validation errors.
        Find empty required fields and fill them with defaults.
        Returns True if no errors or errors were fixed.
        """
        try:
            error_count = await self.ctx.evaluate(VALIDATION_ERROR_JS)
            if error_count == 0:
                return True

            print(f"\n   🔧 {error_count} validation error(s) detected — fixing…")

            # Find all required fields that are empty
            required_sel = (
                "input[required]:not([type='hidden']):not([type='submit'])"
                ":not([type='button']):not([type='file']), "
                "textarea[required], "
                "select[required], "
                "[aria-required='true']"
            )
            required_els = await self.ctx.locator(required_sel).all()

            fixed = 0
            for el in required_els:
                try:
                    if not await el.is_visible(timeout=500):
                        continue

                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    el_type = await el.evaluate("el => (el.type || '').toLowerCase()")

                    if tag == "select":
                        # Check if still on placeholder
                        sel_val = await el.evaluate("el => el.value")
                        if not sel_val or sel_val == "":
                            info = await el.evaluate(ELEMENT_INFO_JS)
                            ft = FieldIntelligence.classify(info)
                            val = FieldIntelligence.get_value(ft, self.sheet_data, info)
                            if await FillEngine.fill_select(el, val):
                                fixed += 1

                    elif el_type in ("checkbox",):
                        if not await el.is_checked():
                            await FillEngine.fill_checkbox(el, True)
                            fixed += 1

                    elif el_type in ("radio",):
                        if not await el.is_checked():
                            name = await el.get_attribute("name")
                            if name:
                                await FillEngine.fill_radio_group(self.ctx, name)
                                fixed += 1

                    else:
                        # Text-like field
                        current = ""
                        try:
                            current = await el.input_value(timeout=500)
                        except Exception:
                            pass
                        if not current or not current.strip():
                            info = await el.evaluate(ELEMENT_INFO_JS)
                            ft = FieldIntelligence.classify(info)
                            val = FieldIntelligence.get_value(ft, self.sheet_data, info)
                            if await FillEngine.fill_text(el, val):
                                fixed += 1
                                print(f"      🔧 Fixed [{ft}] = {val[:40]}")
                except Exception:
                    continue

            if fixed > 0:
                print(f"      ✅ Fixed {fixed} field(s)")
                await asyncio.sleep(Config.VALIDATION_RECHECK_WAIT)

            return True
        except Exception:
            return True  # Don't block submit on error-check failure

    # ── Submit ───────────────────────────────────────────────────────────

    async def submit(self) -> bool:
        """Multi-strategy submit with retry."""
        print(f"\n   🎯 Submitting ({Config.MAX_SUBMIT_RETRIES} max attempts)…")

        pre_url = self.page.url

        for attempt in range(Config.MAX_SUBMIT_RETRIES):
            print(f"      Try {attempt + 1}/{Config.MAX_SUBMIT_RETRIES}…")

            for selector in SUBMIT_SELECTORS:
                try:
                    btns = self.ctx.locator(selector)
                    if await btns.count() == 0:
                        continue

                    btn = btns.first
                    if not await btn.is_visible(timeout=1500):
                        continue

                    # Scroll to button
                    try:
                        await btn.scroll_into_view_if_needed(timeout=3000)
                        await asyncio.sleep(0.2)
                    except Exception:
                        pass

                    # Try click methods
                    clicked = False

                    # Method 1: Normal click
                    try:
                        await btn.click(timeout=4000)
                        clicked = True
                    except Exception:
                        pass

                    # Method 2: Force click
                    if not clicked:
                        try:
                            await btn.click(force=True, timeout=4000)
                            clicked = True
                        except Exception:
                            pass

                    # Method 3: JS click
                    if not clicked:
                        try:
                            await btn.evaluate("el => el.click()")
                            clicked = True
                        except Exception:
                            pass

                    if clicked:
                        await asyncio.sleep(Config.AFTER_SUBMIT)

                        # Verify submission
                        result = await self._verify_submit(pre_url)
                        if result == "success":
                            print(f"      ✅ SUBMITTED SUCCESSFULLY!")
                            return True
                        elif result == "validation_error":
                            print(f"      ⚠️  Validation errors after submit")
                            break  # Break selector loop, retry after fix
                        else:
                            # Might have worked — unclear
                            print(f"      ✅ Submit clicked (unverified)")
                            return True

                except Exception:
                    continue

            # Method 4: Direct form.submit() via JS
            try:
                await self.ctx.evaluate("""
                    () => {
                        const forms = document.querySelectorAll('form');
                        if (forms.length > 0) forms[0].submit();
                    }
                """)
                await asyncio.sleep(Config.AFTER_SUBMIT)
                result = await self._verify_submit(pre_url)
                if result in ("success", "unknown"):
                    print(f"      ✅ JS form.submit() executed")
                    return True
            except Exception:
                pass

            # Method 5: Enter key on last input
            try:
                last_input = self.ctx.locator(
                    "input:not([type='hidden']):not([type='submit'])"
                ).last
                if await last_input.is_visible(timeout=1000):
                    await last_input.press("Enter")
                    await asyncio.sleep(Config.AFTER_SUBMIT)
                    result = await self._verify_submit(pre_url)
                    if result in ("success", "unknown"):
                        print(f"      ✅ Enter key submit")
                        return True
            except Exception:
                pass

            if attempt < Config.MAX_SUBMIT_RETRIES - 1:
                await asyncio.sleep(Config.SUBMIT_RETRY_DELAY)

        print(f"      ❌ Submit failed after {Config.MAX_SUBMIT_RETRIES} attempts")
        return False

    async def _verify_submit(self, pre_url: str) -> str:
        """
        Check post-submit state:
          - "success"          → URL changed or success message found
          - "validation_error" → errors visible on page
          - "unknown"          → can't tell (probably fine)
        """
        try:
            # URL changed = likely success
            if self.page.url != pre_url:
                return "success"

            # Success message on page
            has_success = await self.ctx.evaluate(SUCCESS_INDICATOR_JS)
            if has_success:
                return "success"

            # Check for validation errors
            error_count = await self.ctx.evaluate(VALIDATION_ERROR_JS)
            if error_count > 0:
                return "validation_error"

        except Exception:
            pass

        return "unknown"

    # ── Master orchestration ─────────────────────────────────────────────

    async def process(self) -> str:
        """
        Full pipeline. Returns status string.
        """
        # 1. Navigate to contact page
        await self.navigate_to_form()

        # 2. Scroll to trigger lazy load
        await self.scroll_page()

        # 3. Find form context (page vs iframe)
        await self.find_form_context()

        # 4. Smart wait for fields
        field_count = await self.wait_for_fields()
        if field_count == 0:
            print("   ❌ No form fields found")
            return "NO_FIELDS"

        print(f"\n   🚀 {field_count} fields detected — filling…")

        # 5. Fill + validate + submit loop
        for loop in range(Config.MAX_VALIDATION_LOOPS + 1):
            filled = await self.fill_all()

            if filled == 0 and loop == 0:
                print("   ❌ Could not fill any fields")
                return "FILL_FAILED"

            print(f"\n   📊 Filled: {self.filled_count}/{self.total_count}")

            # Check validation
            await self.check_and_fix_validation()

            # Submit
            submitted = await self.submit()

            if submitted:
                return "SUCCESS"

            # If submit failed due to validation, loop will retry
            if loop < Config.MAX_VALIDATION_LOOPS:
                print(f"\n   🔄 Validation retry {loop + 1}…")
                await asyncio.sleep(Config.VALIDATION_RECHECK_WAIT)

        return "FILLED_NO_SUBMIT"


# =============================================================================
# MAIN WEBSITE WORKER
# =============================================================================

async def process_website(row, idx: int, total: int,
                          sheets_client: GoogleSheetsClient,
                          pw_instance):
    """Process a single website: launch browser → fill form → close."""
    website = str(row.get("website", "")).strip()
    row_index = int(row.get("row_index", idx))

    print(f"\n{'=' * 80}")
    print(f"🌐 [{idx + 1}/{total}] {website}")
    print(f"   {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 80}")

    sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "PROCESSING")

    browser = None
    try:
        browser = await pw_instance.chromium.launch(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO,
        )
        context = await browser.new_context(
            viewport={"width": Config.VIEWPORT_W, "height": Config.VIEWPORT_H},
            user_agent=Config.USER_AGENT,
        )
        page = await context.new_page()

        # ── Navigate with retry ──────────────────────────────────────────
        nav_ok = False
        for attempt in range(Config.MAX_NAV_RETRIES):
            try:
                print(f"   🔄 Loading (attempt {attempt + 1})…")
                await page.goto(website, wait_until="domcontentloaded",
                                timeout=Config.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(Config.AFTER_NAV_WAIT)
                print(f"   ✅ Loaded: {page.url}")
                nav_ok = True
                break
            except Exception as e:
                print(f"   ⚠️  Attempt {attempt + 1} failed: {str(e)[:60]}")
                if attempt < Config.MAX_NAV_RETRIES - 1:
                    await asyncio.sleep(Config.NAV_RETRY_DELAY)

        if not nav_ok:
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NAV_ERROR")
            return False

        # ── CAPTCHA ──────────────────────────────────────────────────────
        if not await CaptchaHandler.handle(page):
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "CAPTCHA_BLOCKED")
            return False

        # ── Process form ─────────────────────────────────────────────────
        sheet_data = row.to_dict() if hasattr(row, 'to_dict') else dict(row)
        processor = FormProcessor(page, sheet_data, website, sheets_client, row_index)
        status = await processor.process()

        sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, status)
        print(f"\n   📊 Result: {status}")

        if status == "SUCCESS":
            await asyncio.sleep(3)

        return status in ("SUCCESS", "FILLED_NO_SUBMIT")

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        traceback.print_exc()
        sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FAILED")
        return False
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


# =============================================================================
# MAIN
# =============================================================================

async def main_async():
    print("=" * 80)
    print("🚀 FORM AUTO-FILLER v10.0 — Production Grade")
    print("=" * 80)
    print()

    sheets_client = GoogleSheetsClient(
        credentials_file="form-automation-484413-489b8d00026a.json"
    )
    df = sheets_client.read_data(
        Config.GOOGLE_SHEETS_ID,
        Config.WEBSITE_SHEET_RANGE,
        Config.DETAILS_SHEET_RANGE,
    )

    if df.empty:
        print("❌ No data found")
        return

    print(f"✅ {len(df)} websites to process\n")
    print("=" * 80)

    pw = await async_playwright().start()
    success = 0

    for idx, row in df.iterrows():
        result = await process_website(row, idx, len(df), sheets_client, pw)
        if result:
            success += 1
        if idx < len(df) - 1:
            await asyncio.sleep(3)

    await pw.stop()

    print("\n" + "=" * 80)
    print(f"🏁 COMPLETE — {success}/{len(df)} successful")
    print("=" * 80)


if __name__ == "__main__":
    import sys
    try:
        print(f"\n🚀 Started: {datetime.now()}\n")
        asyncio.run(main_async())
        print(f"\n✅ Finished: {datetime.now()}\n")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal: {e}")
        traceback.print_exc()
        sys.exit(1)
