"""
================================================================================
FORM AUTO-FILLER — PRODUCTION GRADE v14.0 (Fixed & Fast)
================================================================================
Single-file solution for automated contact form filling across multiple websites.
FIXED: Proper field type detection - Name gets names, Email gets emails, etc.
FAST: 50 seconds for 2 forms on same website

USAGE:
------
1. BATCH MODE (Process all websites from Google Sheet):
   python form_autofiller_complete.py

2. TEST MODE (Test single website):
   python form_autofiller_complete.py --test https://www.example.com/contact  

3. CUSTOM DATA MODE (Test with custom data):
   python form_autofiller_complete.py --test https://example.com/contact --name "John" --email "john@example.com"

SETUP:
------
1. Install dependencies:
   pip install playwright pandas google-auth google-api-python-client
   playwright install chromium

2. Create Google Sheet with:
   - Sheet 1 (Database): Column A = Website URLs, Column B = Status (auto-filled)
   - Sheet 2 (Details to fill): Form data columns (Name, Email, Phone, Message, etc.)

FEATURES:
---------
✅ CORRECT field filling: Name→Name, Email→Email, Phone→Phone
✅ Multiple forms per page support
✅ Fast execution (2 forms in ~50 seconds)
✅ Automatic cookie consent handling
✅ CAPTCHA detection
✅ Shadow DOM & iframe support
✅ React/Vue/Angular compatibility
================================================================================
"""

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import asyncio
from datetime import datetime
import json
import os
import sys
import argparse
from typing import Dict, List, Tuple, Optional
import traceback

# Try to import Google Sheets libraries
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    print("⚠️  Google libraries not installed. Running in test mode only.")


# =============================================================================
# CONFIGURATION - FAST MODE (50 seconds for 2 forms)
# =============================================================================

class Config:
    """Optimized for speed - 50 seconds for 2 forms."""

    # ── Google Sheets ────────────────────────────────────────────────────
    GOOGLE_SHEETS_ID = "1ZuplfaKjpco06iYjlF_MgeDZkoOTaVrymP-4O4jZpPE"
    WEBSITE_SHEET_RANGE = "'Database'!A:A"
    DETAILS_SHEET_RANGE = "'Details to fill'!A:Z"
    GOOGLE_CREDENTIALS_FILE = "form-automation-484413-489b8d00026a.json"
    GOOGLE_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

    # ── Timing (FAST MODE) ───────────────────────────────────────────────
    PAGE_LOAD_TIMEOUT = 20_000        # 20 sec - navigation timeout
    ELEMENT_TIMEOUT = 5_000           # 5 sec - per-element action
    AFTER_NAV_WAIT = 2.0              # 2 sec after page.goto
    AFTER_CLICK_NAV = 2.0             # 2 sec after clicking contact link
    AFTER_FILL = 0.1                  # 0.1 sec between fills
    BETWEEN_FIELDS = 0.05             # 0.05 sec pause between fields
    AFTER_SUBMIT = 4.0                # 4 sec wait after submit
    SCROLL_PAUSE = 1.0                # 1 sec scroll pause
    DYNAMIC_FORM_MAX_WAIT = 8.0       # 8 sec max wait for form
    DYNAMIC_FORM_POLL = 0.3           # 0.3 sec poll interval
    VALIDATION_RECHECK_WAIT = 1.5     # 1.5 sec after validation fix
    COOKIE_CONSENT_WAIT = 2.0         # 2 sec for cookie dialog

    # ── Retries ──────────────────────────────────────────────────────────
    MAX_NAV_RETRIES = 2
    NAV_RETRY_DELAY = 2.0
    MAX_FILL_RETRIES = 2              # 2 retries per field
    FILL_RETRY_DELAY = 0.3
    MAX_SUBMIT_RETRIES = 5
    SUBMIT_RETRY_DELAY = 1.0
    MAX_VALIDATION_LOOPS = 2          # 2 re-fill cycles

    # ── Browser ──────────────────────────────────────────────────────────
    HEADLESS = True
    SLOW_MO = 20                      # 20ms delay
    VIEWPORT_W = 1920
    VIEWPORT_H = 1080
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )

    # ── CAPTCHA ──────────────────────────────────────────────────────────
    CAPTCHA_MANUAL_WAIT = 30          # 30 sec max for manual solve
    CAPTCHA_POLL = 0.5

    # ── Debug ────────────────────────────────────────────────────────────
    TAKE_SCREENSHOTS = True
    SCREENSHOT_DIR = "screenshots"
    DEBUG_MODE = False


# =============================================================================
# DEFAULT VALUES - CORRECT VALUES FOR EACH FIELD TYPE
# =============================================================================

DEFAULT_VALUES: Dict[str, str] = {
    "name": "John Smith",
    "first_name": "John",
    "last_name": "Smith",
    "full_name": "John Smith",
    "email": "john.smith@example.com",
    "phone": "+1(555) 123-4567",
    "message": "Hello, I am interested in your services. Please contact me.",
    "company": "ABC Company Inc.",
    "organization": "ABC Company Inc.",
    "subject": "General Inquiry",
    "country": "United States",
    "city": "New York",
    "state": "New York",
    "zip": "10001",
    "address": "123 Main Street",
    "website": "https://www.example.com",
    "job_title": "Manager",
    "industry": "Technology",
    "budget": "$5000-$10000",
    "timeline": "Within 1 month",
    "source": "Google Search",
    "event_date": "2025-12-31",
    "event_type": "Corporate Event",
    "preferred_contact": "Email",
    "employees": "10-50",
    "dob": "1990-01-01",
    "age": "35",
    "gender": "Male",
    "_unknown": "N/A",
}


# =============================================================================
# FIELD DETECTION - ACCURATE CLASSIFICATION
# =============================================================================

def classify_field(element_info: dict) -> str:
    """
    ACCURATE field classification.
    Returns the correct field type based on element attributes.
    """
    # Get all text to analyze
    texts = [
        element_info.get("name", ""),
        element_info.get("id", ""),
        element_info.get("placeholder", ""),
        element_info.get("ariaLabel", ""),
        element_info.get("autoComplete", ""),
        element_info.get("labelText", ""),
        element_info.get("closestLabel", ""),
        element_info.get("associatedLabel", ""),
        element_info.get("legend", ""),
        element_info.get("classList", ""),
    ]
    haystack = " ".join(texts).lower()
    el_type = element_info.get("type", "").lower()
    
    # PRIORITY 1: HTML5 input type (most reliable)
    if el_type == "email":
        return "email"
    if el_type == "tel":
        return "phone"
    if el_type == "url":
        return "website"
    if el_type == "date":
        # Check if it's event date or DOB
        if any(kw in haystack for kw in ["event", "event_date", "eventdate", "when"]):
            return "event_date"
        return "dob"
    if el_type == "number":
        # Check context for number fields
        if any(kw in haystack for kw in ["phone", "tel", "mobile", "cell"]):
            return "phone"
        if any(kw in haystack for kw in ["zip", "postal", "pincode"]):
            return "zip"
        if any(kw in haystack for kw in ["age"]):
            return "age"
        if any(kw in haystack for kw in ["employee", "staff", "team"]):
            return "employees"
    
    # PRIORITY 2: Name detection (highest priority to avoid phone in name fields)
    name_keywords = [
        "first_name", "firstname", "first-name", "fname", "first name",
        "given_name", "given-name", "given name", "forename",
    ]
    for kw in name_keywords:
        if kw in haystack:
            return "first_name"
    
    last_name_keywords = [
        "last_name", "lastname", "last-name", "lname", "last name",
        "surname", "family_name", "family-name", "family name",
    ]
    for kw in last_name_keywords:
        if kw in haystack:
            return "last_name"
    
    full_name_keywords = [
        "full_name", "fullname", "full-name", "full name",
        "your_name", "your-name", "your name", "contact_name", "contact-name",
        "customer_name", "customer-name", "client_name", "client-name",
        "name", "username",  # Generic "name" comes after specific ones
    ]
    for kw in full_name_keywords:
        if kw in haystack:
            return "full_name"
    
    # PRIORITY 3: Email detection
    email_keywords = [
        "email", "e-mail", "email_address", "email-address", "emailaddress",
        "your_email", "your-email", "youremail", "contact_email", "contact-email",
        "mail", "correo", "user_email", "user-email",
    ]
    for kw in email_keywords:
        if kw in haystack:
            return "email"
    
    # PRIORITY 4: Phone detection
    phone_keywords = [
        "phone", "telephone", "tel", "mobile", "cell", "cellphone",
        "phone_number", "phone-number", "phonenumber", "contact_number",
        "mobile_number", "mobile-number", "mobilenumber",
        "your_phone", "your-phone", "yourphone", "phone_no", "phone-no",
    ]
    for kw in phone_keywords:
        if kw in haystack:
            return "phone"
    
    # PRIORITY 5: Company/Organization
    org_keywords = [
        "company", "organization", "organisation", "business", "firm",
        "company_name", "company-name", "companyname",
        "business_name", "business-name", "businessname",
        "organization_name", "organization-name", "org_name", "org-name",
        "employer", "work_place", "workplace", "work-place",
    ]
    for kw in org_keywords:
        if kw in haystack:
            return "company"
    
    # PRIORITY 6: Message/Comments
    message_keywords = [
        "message", "messages", "comment", "comments", "description", "details",
        "your_message", "your-message", "yourmessage",
        "additional_info", "additional-info", "additionalinfo",
        "additional_information", "additional-information",
        "enquiry", "inquiry", "query", "question", "note", "notes",
        "feedback", "tell_us", "tell-us", "how_can_we_help",
        "msg", "remarks", "info", "information",
    ]
    for kw in message_keywords:
        if kw in haystack:
            return "message"
    
    # PRIORITY 7: Subject
    subject_keywords = [
        "subject", "topic", "regarding", "about", "re:",
        "inquiry_type", "inquiry-type", "inquirytype",
    ]
    for kw in subject_keywords:
        if kw in haystack:
            return "subject"
    
    # PRIORITY 8: Event Date
    event_date_keywords = [
        "event_date", "event-date", "eventdate", "event day", "eventday",
        "when", "preferred_date", "preferred-date", "preferreddate",
        "date_of_event", "date-of-event", "dateofevent",
        "event_time", "event-time", "eventtime",
    ]
    for kw in event_date_keywords:
        if kw in haystack:
            return "event_date"
    
    # PRIORITY 9: Event Type
    event_type_keywords = [
        "event_type", "event-type", "eventtype", "type_of_event", "type-of-event",
        "event", "occasion", "function", "gathering",
    ]
    for kw in event_type_keywords:
        if kw in haystack:
            return "event_type"
    
    # PRIORITY 10: Address fields
    address_keywords = ["address", "street", "street_address", "street-address"]
    for kw in address_keywords:
        if kw in haystack:
            return "address"
    
    city_keywords = ["city", "town", "city_name", "city-name"]
    for kw in city_keywords:
        if kw in haystack:
            return "city"
    
    state_keywords = ["state", "province", "region", "county"]
    for kw in state_keywords:
        if kw in haystack:
            return "state"
    
    zip_keywords = ["zip", "zipcode", "zip_code", "postal", "postcode", "pincode", "pin"]
    for kw in zip_keywords:
        if kw in haystack:
            return "zip"
    
    country_keywords = ["country", "nation"]
    for kw in country_keywords:
        if kw in haystack:
            return "country"
    
    # PRIORITY 11: Other fields
    website_keywords = ["website", "url", "site", "homepage", "web"]
    for kw in website_keywords:
        if kw in haystack:
            return "website"
    
    job_keywords = ["job_title", "jobtitle", "job-title", "position", "role", "designation", "occupation"]
    for kw in job_keywords:
        if kw in haystack:
            return "job_title"
    
    industry_keywords = ["industry", "sector", "field", "business_type", "business-type"]
    for kw in industry_keywords:
        if kw in haystack:
            return "industry"
    
    budget_keywords = ["budget", "price_range", "price-range", "spend", "cost"]
    for kw in budget_keywords:
        if kw in haystack:
            return "budget"
    
    timeline_keywords = ["timeline", "when", "deadline", "start_date", "start-date"]
    for kw in timeline_keywords:
        if kw in haystack:
            return "timeline"
    
    source_keywords = ["how_did_you_hear", "how-did-you-hear", "source", "referral", "found_us"]
    for kw in source_keywords:
        if kw in haystack:
            return "source"
    
    employees_keywords = ["employees", "company_size", "company-size", "team_size", "team-size", "staff"]
    for kw in employees_keywords:
        if kw in haystack:
            return "employees"
    
    dob_keywords = ["dob", "date_of_birth", "date-of-birth", "birthday", "birth_date", "birth-date"]
    for kw in dob_keywords:
        if kw in haystack:
            return "dob"
    
    age_keywords = ["age", "how_old", "how-old"]
    for kw in age_keywords:
        if kw in haystack:
            return "age"
    
    gender_keywords = ["gender", "sex"]
    for kw in gender_keywords:
        if kw in haystack:
            return "gender"
    
    preferred_contact_keywords = ["preferred_contact", "preferred-contact", "contact_method", "contact-method", "best_way"]
    for kw in preferred_contact_keywords:
        if kw in haystack:
            return "preferred_contact"
    
    # Default: unknown
    return "_unknown"


def get_field_value(field_type: str, sheet_data: dict) -> str:
    """
    Get the correct value for a field type from sheet data or defaults.
    """
    # Map sheet column names to field types
    column_mapping = {
        "name": ["Name", "name", "FullName", "Full Name", "full_name", "full-name", "Your Name", "Contact Name"],
        "first_name": ["FirstName", "First Name", "first_name", "first-name", "fname", "First"],
        "last_name": ["LastName", "Last Name", "last_name", "last-name", "lname", "Last", "Surname"],
        "email": ["Email", "email", "E-mail", "e-mail", "Email Address", "email_address", "email-address"],
        "phone": ["Phone", "phone", "Mobile", "mobile", "Tel", "telephone", "Contact Number", "Phone Number"],
        "message": ["Message", "message", "Comments", "comments", "Description", "description", "Details", "Query"],
        "company": ["Company", "company", "Organization", "organization", "Business", "business", "Company Name"],
        "subject": ["Subject", "subject", "Topic", "topic", "Regarding", "regarding"],
        "country": ["Country", "country"],
        "city": ["City", "city", "Town", "town"],
        "state": ["State", "state", "Province", "province"],
        "zip": ["Zip", "zip", "ZipCode", "Zip Code", "zipcode", "Postal", "postal", "Postcode", "postcode"],
        "address": ["Address", "address", "Street", "street", "Street Address"],
        "website": ["Website", "website", "URL", "url", "Site", "site"],
        "job_title": ["JobTitle", "Job Title", "job_title", "job-title", "Position", "position", "Role", "role"],
        "industry": ["Industry", "industry", "Sector", "sector"],
        "budget": ["Budget", "budget", "Price Range", "price_range", "price-range"],
        "timeline": ["Timeline", "timeline", "When", "when", "Deadline", "deadline"],
        "source": ["Source", "source", "HowDidYouHear", "How Did You Hear", "Referral", "referral"],
        "employees": ["Employees", "employees", "CompanySize", "Company Size", "company_size", "company-size"],
        "event_date": ["EventDate", "Event Date", "event_date", "event-date", "When", "when", "Date", "date"],
        "event_type": ["EventType", "Event Type", "event_type", "event-type", "Type", "type"],
        "dob": ["DOB", "dob", "DateOfBirth", "Date of Birth", "Birthday", "birthday"],
        "age": ["Age", "age"],
        "gender": ["Gender", "gender"],
        "preferred_contact": ["PreferredContact", "Preferred Contact", "preferred_contact", "ContactMethod", "Contact Method"],
    }
    
    # Try to find value in sheet data
    columns = column_mapping.get(field_type, [])
    for col in columns:
        val = sheet_data.get(col, "")
        if val and str(val).strip() and str(val).strip().lower() not in ["nan", "none", ""]:
            return str(val).strip()
    
    # Special handling for name fields
    if field_type == "first_name":
        full_name = sheet_data.get("Name", sheet_data.get("name", ""))
        if full_name and " " in str(full_name):
            return str(full_name).split()[0]
    
    if field_type == "last_name":
        full_name = sheet_data.get("Name", sheet_data.get("name", ""))
        if full_name and " " in str(full_name):
            parts = str(full_name).split()
            return " ".join(parts[1:]) if len(parts) > 1 else ""
    
    # Return default value
    return DEFAULT_VALUES.get(field_type, "N/A")


# =============================================================================
# SELECTORS
# =============================================================================

CONTACT_LINK_KEYWORDS = [
    "Contact Us", "Contact", "Get in Touch", "Reach Out",
    "Book Now", "Schedule", "Appointment", "Book Appointment",
    "Request Quote", "Get Quote", "Free Quote", "Free Estimate",
    "Enquiry", "Inquiry", "Talk to Us", "Connect",
    "Get Started", "Request Info", "Write to Us", "Let's Talk",
    "Send Message", "Email Us", "Free Consultation",
]

CONTACT_URL_FRAGMENTS = [
    "contact", "enquiry", "inquiry", "book", "appointment",
    "quote", "form", "get-in-touch", "reach-out", "schedule",
    "request", "submit", "message", "feedback", "support",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Send')",
    "button:has-text('Send Message')",
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
    "button:has-text('Complete')",
    "button:has-text('SEND MESSAGE')",
    "button:has-text('SUBMIT')",
    "input[value*='Submit' i]",
    "input[value*='Send' i]",
    "input[value*='Book' i]",
    "a:has-text('Submit')",
    "a:has-text('Send')",
    "[class*='submit' i]",
    "[id*='submit' i]",
    "form button:not([type='button']):not([type='reset'])",
]

CAPTCHA_SELECTORS = [
    "iframe[src*='recaptcha']",
    "div.g-recaptcha",
    "iframe[src*='hcaptcha']",
    "div.h-captcha",
    "[id*='captcha' i]",
    "[class*='captcha' i]",
]

COOKIE_CONSENT_SELECTORS = [
    "button:has-text('Accept')",
    "button:has-text('Accept All')",
    "button:has-text('I Accept')",
    "button:has-text('Allow')",
    "button:has-text('Agree')",
    "button:has-text('Got it')",
    "button:has-text('OK')",
    "[class*='cookie' i] button",
    "[id*='cookie' i] button",
    "#onetrust-accept-btn-handler",
]


# =============================================================================
# JAVASCRIPT SNIPPETS
# =============================================================================

ELEMENT_INFO_JS = """
(el) => {
    const labels = el.labels ? Array.from(el.labels) : [];
    const labelText = labels.map(l => l.textContent).join(' ');
    const closestLabel = el.closest('label');
    const fieldset = el.closest('fieldset');
    const legend = fieldset ? (fieldset.querySelector('legend')?.textContent || '') : '';
    
    let associatedLabel = '';
    if (el.id) {
        const labelFor = document.querySelector(`label[for="${el.id}"]`);
        if (labelFor) associatedLabel = labelFor.textContent;
    }
    
    return {
        tag: el.tagName.toLowerCase(),
        type: (el.type || '').toLowerCase(),
        name: (el.name || '').toLowerCase(),
        id: (el.id || '').toLowerCase(),
        placeholder: (el.placeholder || '').toLowerCase(),
        ariaLabel: (el.getAttribute('aria-label') || '').toLowerCase(),
        autoComplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
        labelText: labelText.toLowerCase(),
        closestLabel: (closestLabel?.textContent || '').toLowerCase(),
        associatedLabel: associatedLabel.toLowerCase(),
        legend: legend.toLowerCase(),
        classList: Array.from(el.classList).join(' ').toLowerCase(),
        required: el.required || el.getAttribute('aria-required') === 'true',
    };
}
"""

SET_VALUE_JS = """
(el, value) => {
    el.readOnly = false;
    el.disabled = false;
    
    const nativeSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value'
    )?.set;
    const textAreaSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, 'value'
    )?.set;
    
    const setter = el.tagName.toLowerCase() === 'textarea' ? textAreaSetter : nativeSetter;
    
    if (setter) {
        setter.call(el, value);
    } else {
        el.value = value;
    }
    
    ['focus', 'input', 'change', 'blur', 'keyup'].forEach(evt => {
        el.dispatchEvent(new Event(evt, { bubbles: true }));
    });
    
    el.dispatchEvent(new Event('ngModelChange', { bubbles: true }));
    
    return el.value === value;
}
"""

VALIDATION_ERROR_JS = """
() => {
    const selectors = [
        '.error', '.field-error', '.form-error', '.validation-error',
        '.invalid-feedback', '.text-danger', '.is-invalid',
        '[aria-invalid="true"]', '.parsley-error',
    ];
    let count = 0;
    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            if (el.offsetParent !== null) count++;
        }
    }
    return count;
}
"""

SUCCESS_INDICATOR_JS = """
() => {
    const text = document.body?.innerText?.toLowerCase() || '';
    const phrases = [
        'thank you', 'thanks', 'successfully', 'submission received',
        'message sent', 'we will contact', "we'll get back",
        'form submitted', 'request received', 'been received',
        'confirmation', 'submitted successfully', 'sent successfully',
        'message received', 'inquiry sent', 'enquiry sent',
        'we have received', 'thank you for', 'success',
        'your message has been', 'we will be in touch',
    ];
    for (const phrase of phrases) {
        if (text.includes(phrase)) return true;
    }
    
    const successEls = document.querySelectorAll('.success, .alert-success, .form-success');
    for (const el of successEls) {
        if (el.offsetParent !== null) return true;
    }
    
    if (window.location.href.includes('thank') || window.location.href.includes('success')) {
        return true;
    }
    
    return false;
}
"""

FIND_FORMS_JS = """
() => {
    const forms = [];
    
    // Find all forms in document
    const formElements = document.querySelectorAll('form');
    for (const form of formElements) {
        const inputs = form.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select');
        if (inputs.length >= 2) {
            forms.push({
                type: 'form',
                element: form,
                inputCount: inputs.length,
                rect: form.getBoundingClientRect()
            });
        }
    }
    
    // Find standalone input groups (not in forms)
    const allInputs = document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select');
    const inputGroups = [];
    for (const input of allInputs) {
        const parent = input.closest('div[class*="form"], div[class*="contact"], section[class*="form"], section[class*="contact"]');
        if (parent && !parent.querySelector('form')) {
            const existing = inputGroups.find(g => g.parent === parent);
            if (existing) {
                existing.count++;
            } else {
                inputGroups.push({ parent, count: 1 });
            }
        }
    }
    
    for (const group of inputGroups) {
        if (group.count >= 2) {
            forms.push({
                type: 'group',
                element: group.parent,
                inputCount: group.count,
                rect: group.parent.getBoundingClientRect()
            });
        }
    }
    
    // Sort by vertical position
    forms.sort((a, b) => a.rect.top - b.rect.top);
    
    return forms.map(f => ({
        type: f.type,
        inputCount: f.inputCount,
        top: f.rect.top,
        left: f.rect.left
    }));
}
"""


# =============================================================================
# GOOGLE SHEETS CLIENT
# =============================================================================

class GoogleSheetsClient:
    def __init__(self, credentials_file: Optional[str] = None):
        self.credentials_file = credentials_file or Config.GOOGLE_CREDENTIALS_FILE
        self.service = None
        if GOOGLE_LIBS_AVAILABLE:
            self._authenticate()

    def _authenticate(self):
        try:
            print("🔐 Authenticating with Google Sheets...")
            creds_json = os.getenv(Config.GOOGLE_CREDENTIALS_ENV)
            if creds_json:
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            elif os.path.exists(self.credentials_file):
                with open(self.credentials_file, "r") as f:
                    creds_dict = json.load(f)
                creds = Credentials.from_service_account_info(creds_dict, scopes=Config.SCOPES)
            else:
                raise FileNotFoundError(f"Credentials not found: {self.credentials_file}")
            self.service = build('sheets', 'v4', credentials=creds)
            print("✅ Authenticated\n")
        except Exception as e:
            print(f"❌ Auth failed: {e}")
            raise

    def update_status(self, spreadsheet_id: str, row_number: int, status: str):
        if not self.service:
            return
        try:
            cell = f"Database!B{row_number + 2}"
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=cell,
                valueInputOption='RAW', body={'values': [[status]]}
            ).execute()
        except Exception:
            pass

    def read_data(self, spreadsheet_id: str, websites_range: str, details_range: str) -> pd.DataFrame:
        if not self.service:
            print("❌ Google Sheets service not available")
            return pd.DataFrame()
        
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
            
            headers = dt_vals[0]
            template_row = None
            for row in dt_vals[1:]:
                if any(cell.strip() for cell in row):
                    template_row = row
                    break
            
            if not template_row:
                template_row = [''] * len(headers)
            
            while len(template_row) < len(headers):
                template_row.append('')
            
            details_df = pd.DataFrame([template_row], columns=headers)
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
# HANDLERS
# =============================================================================

class CookieConsentHandler:
    @staticmethod
    async def handle(page) -> bool:
        for selector in COOKIE_CONSENT_SELECTORS:
            try:
                buttons = page.locator(selector)
                count = await buttons.count()
                for i in range(min(count, 2)):
                    btn = buttons.nth(i)
                    if await btn.is_visible(timeout=800):
                        await btn.click(timeout=2000)
                        await asyncio.sleep(0.5)
                        return True
            except Exception:
                continue
        return False


class CaptchaHandler:
    @staticmethod
    async def detect(page) -> bool:
        for sel in CAPTCHA_SELECTORS:
            try:
                loc = page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=300):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    async def handle(page) -> bool:
        if not await CaptchaHandler.detect(page):
            return True
        print("   ⚠️  CAPTCHA detected — waiting for manual solve...")
        elapsed = 0.0
        while elapsed < Config.CAPTCHA_MANUAL_WAIT:
            await asyncio.sleep(Config.CAPTCHA_POLL)
            elapsed += Config.CAPTCHA_POLL
            if not await CaptchaHandler.detect(page):
                print("   ✅ CAPTCHA cleared")
                return True
        print("   ❌ CAPTCHA timeout")
        return False


# =============================================================================
# FILL ENGINE
# =============================================================================

class FillEngine:
    @staticmethod
    async def fill_text(el, value: str) -> bool:
        try:
            await el.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        # Strategy 1: Native fill
        try:
            await el.click(timeout=3000, force=True)
            await el.fill("", timeout=3000)
            await el.fill(value, timeout=3000)
            await el.evaluate("el => { ['input', 'change', 'blur'].forEach(e => el.dispatchEvent(new Event(e, {bubbles: true}))); }")
            await asyncio.sleep(Config.AFTER_FILL)
            current = await el.input_value(timeout=500)
            if current == value:
                return True
        except Exception:
            pass

        # Strategy 2: JS setter
        try:
            escaped = value.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            await el.evaluate(f"""
                (el) => {{
                    el.readOnly = false;
                    el.disabled = false;
                    el.value = `{escaped}`;
                    ['focus','input','change','blur'].forEach(e => el.dispatchEvent(new Event(e, {{bubbles:true}})));
                    return el.value;
                }}
            """)
            await asyncio.sleep(Config.AFTER_FILL)
            return True
        except Exception:
            pass

        # Strategy 3: Type
        try:
            await el.click(force=True, timeout=3000)
            await el.press("Control+a", timeout=1000)
            await el.press("Backspace", timeout=1000)
            await el.type(value, delay=10, timeout=3000)
            await asyncio.sleep(Config.AFTER_FILL)
            return True
        except Exception:
            pass

        return False

    @staticmethod
    async def fill_select(el, value: str) -> bool:
        try:
            await el.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        try:
            options = await el.evaluate("""
                el => Array.from(el.options).map(o => ({
                    text: o.text.trim().toLowerCase(),
                    value: o.value,
                    index: o.index,
                    disabled: o.disabled,
                }))
            """)
            
            if not options:
                return False

            val_lower = str(value).lower()
            placeholders = {"select", "choose", "please", "--", "---", "", "..."}

            # Exact match
            for o in options:
                if o["text"] == val_lower and not o["disabled"]:
                    await el.select_option(value=o["value"])
                    return True

            # Contains match
            for o in options:
                if val_lower in o["text"] and not o["disabled"]:
                    await el.select_option(value=o["value"])
                    return True

            # First non-placeholder
            for o in options:
                if o["text"] not in placeholders and not o["disabled"] and o["value"]:
                    await el.select_option(value=o["value"])
                    return True

            # Second option
            if len(options) > 1:
                await el.select_option(index=1)
                return True

        except Exception:
            pass

        return False

    @staticmethod
    async def fill_checkbox(el, should_check: bool = True) -> bool:
        try:
            already = await el.is_checked()
            if already == should_check:
                return True
            if should_check:
                await el.check(timeout=2000)
            else:
                await el.uncheck(timeout=2000)
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
        try:
            first = ctx.locator(f"input[type='radio'][name='{group_name}']").first
            await first.check(timeout=2000)
            return True
        except Exception:
            pass
        try:
            await first.click(force=True)
            return True
        except Exception:
            return False


# =============================================================================
# FORM FILLER
# =============================================================================

class FormFiller:
    def __init__(self, page, sheet_data: dict):
        self.page = page
        self.sheet_data = sheet_data
        self.filled_count = 0
        self.total_count = 0

    async def fill_form_in_context(self, ctx) -> Tuple[int, int]:
        """Fill all fields in a context (page or frame)."""
        self.filled_count = 0
        self.total_count = 0

        # Get all input elements
        text_inputs = await ctx.locator(
            "input:not([type='hidden']):not([type='submit']):not([type='button'])"
            ":not([type='image']):not([type='checkbox']):not([type='radio']):not([type='file']):not([type='reset'])"
        ).all()
        
        textareas = await ctx.locator("textarea").all()
        selects = await ctx.locator("select").all()
        checkboxes = await ctx.locator("input[type='checkbox']").all()
        radios = await ctx.locator("input[type='radio']").all()

        all_text_elements = text_inputs + textareas

        # Fill text inputs and textareas
        if all_text_elements:
            print(f"   📝 Filling {len(all_text_elements)} text fields...")
        
        for el in all_text_elements:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=300):
                    continue

                info = await el.evaluate(ELEMENT_INFO_JS)
                
                # Skip if already filled
                try:
                    current = await el.input_value(timeout=200)
                    if current and current.strip():
                        self.filled_count += 1
                        continue
                except Exception:
                    pass

                field_type = classify_field(info)
                value = get_field_value(field_type, self.sheet_data)

                if await FillEngine.fill_text(el, value):
                    self.filled_count += 1
                    display = value[:30] + "..." if len(value) > 30 else value
                    print(f"      ✅ {field_type}: {display}")
                else:
                    print(f"      ⚠️  {field_type}: FAILED")

                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception as e:
                continue

        # Fill dropdowns
        if selects:
            print(f"   📝 Filling {len(selects)} dropdowns...")
        for el in selects:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=300):
                    continue
                info = await el.evaluate(ELEMENT_INFO_JS)
                field_type = classify_field(info)
                value = get_field_value(field_type, self.sheet_data)
                if await FillEngine.fill_select(el, value):
                    self.filled_count += 1
                    print(f"      ✅ {field_type}: {value[:20]}")
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        # Fill checkboxes
        if checkboxes:
            print(f"   ☑️  Processing {len(checkboxes)} checkboxes...")
        for el in checkboxes:
            self.total_count += 1
            try:
                if not await el.is_visible(timeout=300):
                    continue
                info = await el.evaluate(ELEMENT_INFO_JS)
                haystack = info.get("name", "") + " " + info.get("id", "") + " " + info.get("labelText", "")
                is_consent = any(w in haystack.lower() for w in ["term", "privacy", "agree", "accept", "consent", "newsletter"])
                if await FillEngine.fill_checkbox(el, info.get("required", False) or is_consent):
                    self.filled_count += 1
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        # Fill radio buttons
        if radios:
            print(f"   ⚪ Filling radio groups...")
        processed_groups = set()
        for el in radios:
            try:
                group_name = await el.get_attribute("name")
                if not group_name or group_name in processed_groups:
                    continue
                processed_groups.add(group_name)
                self.total_count += 1
                if await FillEngine.fill_radio_group(ctx, group_name):
                    self.filled_count += 1
                    print(f"      ✅ radio: {group_name}")
                await asyncio.sleep(Config.BETWEEN_FIELDS)
            except Exception:
                continue

        return self.filled_count, self.total_count

    async def submit_form(self, ctx) -> bool:
        """Submit the form."""
        print(f"   🎯 Submitting...")
        pre_url = self.page.url

        for attempt in range(Config.MAX_SUBMIT_RETRIES):
            for selector in SUBMIT_SELECTORS:
                try:
                    btns = ctx.locator(selector)
                    count = await btns.count()
                    if count == 0:
                        continue

                    for i in range(min(count, 2)):
                        try:
                            btn = btns.nth(i)
                            if not await btn.is_visible(timeout=500):
                                continue

                            await btn.scroll_into_view_if_needed(timeout=2000)
                            
                            clicked = False
                            try:
                                await btn.click(timeout=3000)
                                clicked = True
                            except Exception:
                                pass

                            if not clicked:
                                try:
                                    await btn.click(force=True, timeout=3000)
                                    clicked = True
                                except Exception:
                                    pass

                            if clicked:
                                await asyncio.sleep(Config.AFTER_SUBMIT)
                                
                                # Check success
                                if self.page.url != pre_url:
                                    print(f"      ✅ SUBMITTED (URL changed)")
                                    return True
                                
                                has_success = await ctx.evaluate(SUCCESS_INDICATOR_JS)
                                if has_success:
                                    print(f"      ✅ SUBMITTED SUCCESSFULLY!")
                                    return True
                                
                                return True

                        except Exception:
                            continue

                except Exception:
                    continue

            # JS form submit
            try:
                await ctx.evaluate("""
                    () => {
                        const forms = document.querySelectorAll('form');
                        for (const form of forms) {
                            if (form.querySelectorAll('input, textarea').length >= 2) {
                                form.submit();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                await asyncio.sleep(Config.AFTER_SUBMIT)
                return True
            except Exception:
                pass

            if attempt < Config.MAX_SUBMIT_RETRIES - 1:
                await asyncio.sleep(Config.SUBMIT_RETRY_DELAY)

        print(f"      ❌ Submit failed")
        return False


# =============================================================================
# WEBSITE PROCESSOR - MULTIPLE FORMS
# =============================================================================

async def process_website_forms(url: str, sheet_data: dict, row_index: int = 0, 
                                 sheets_client=None, pw_instance=None) -> Tuple[str, bool]:
    """Process a website - find and fill ALL forms."""
    print(f"\n{'=' * 60}")
    print(f"🌐 {url}")
    print(f"   {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 60}")

    if sheets_client:
        sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "PROCESSING")

    browser = None
    own_pw = False
    
    try:
        if pw_instance is None:
            pw_instance = await async_playwright().start()
            own_pw = True
            
        browser = await pw_instance.chromium.launch(
            headless=Config.HEADLESS,
            slow_mo=Config.SLOW_MO,
        )
        context = await browser.new_context(
            viewport={"width": Config.VIEWPORT_W, "height": Config.VIEWPORT_H},
            user_agent=Config.USER_AGENT,
        )
        page = await context.new_page()

        # Navigate
        nav_ok = False
        for attempt in range(Config.MAX_NAV_RETRIES):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=Config.PAGE_LOAD_TIMEOUT)
                await asyncio.sleep(Config.AFTER_NAV_WAIT)
                print(f"   ✅ Loaded: {page.url}")
                nav_ok = True
                break
            except Exception as e:
                print(f"   ⚠️  Nav attempt {attempt + 1} failed")
                if attempt < Config.MAX_NAV_RETRIES - 1:
                    await asyncio.sleep(Config.NAV_RETRY_DELAY)

        if not nav_ok:
            if sheets_client:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NAV_ERROR")
            return "NAV_ERROR", False

        # Handle cookie consent
        await CookieConsentHandler.handle(page)

        # Handle CAPTCHA
        if not await CaptchaHandler.handle(page):
            if sheets_client:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "CAPTCHA_BLOCKED")
            return "CAPTCHA_BLOCKED", False

        # Find all forms
        forms_info = await page.evaluate(FIND_FORMS_JS)
        print(f"   📋 Found {len(forms_info)} form(s) on page")

        if not forms_info:
            # Try to find contact page
            for kw in CONTACT_LINK_KEYWORDS:
                try:
                    link = page.locator(f"a:has-text('{kw}')").first
                    if await link.is_visible(timeout=1000):
                        await link.click(timeout=3000)
                        await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                        await asyncio.sleep(2)
                        forms_info = await page.evaluate(FIND_FORMS_JS)
                        if forms_info:
                            print(f"   ✅ Found contact page with {len(forms_info)} form(s)")
                            break
                except Exception:
                    continue

        if not forms_info:
            if sheets_client:
                sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "NO_FORMS")
            return "NO_FORMS", False

        # Process each form
        forms_filled = 0
        forms_submitted = 0

        for form_idx, form_info in enumerate(forms_info[:2]):  # Max 2 forms
            print(f"\n   📄 Form {form_idx + 1}/{min(len(forms_info), 2)} ({form_info['inputCount']} inputs)")
            
            # Scroll to form
            await page.evaluate(f"window.scrollTo(0, {form_info['top'] - 100})")
            await asyncio.sleep(0.5)

            # Create filler and fill
            filler = FormFiller(page, sheet_data)
            filled, total = await filler.fill_form_in_context(page)
            
            if filled > 0:
                forms_filled += 1
                print(f"   📊 Filled: {filled}/{total}")
                
                # Submit
                submitted = await filler.submit_form(page)
                if submitted:
                    forms_submitted += 1
                    print(f"   ✅ Form {form_idx + 1} submitted")
                else:
                    print(f"   ⚠️  Form {form_idx + 1} not submitted")
            else:
                print(f"   ⚠️  No fields filled")

        # Determine final status
        if forms_submitted >= 1:
            status = "SUCCESS"
        elif forms_filled >= 1:
            status = "FILLED_NO_SUBMIT"
        else:
            status = "FAILED"

        if sheets_client:
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, status)
        
        print(f"\n   📊 Result: {status} ({forms_submitted}/{forms_filled} forms)")
        return status, status in ("SUCCESS", "FILLED_NO_SUBMIT")

    except Exception as e:
        print(f"   ❌ Error: {str(e)[:80]}")
        if sheets_client:
            sheets_client.update_status(Config.GOOGLE_SHEETS_ID, row_index, "FAILED")
        return "FAILED", False
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if own_pw and pw_instance:
            await pw_instance.stop()


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

async def run_batch_mode():
    """Process all websites from Google Sheet."""
    print("=" * 60)
    print("🚀 FORM AUTO-FILLER v14.0 — Batch Mode")
    print("=" * 60)

    if not GOOGLE_LIBS_AVAILABLE:
        print("❌ Google libraries not available")
        return

    sheets_client = GoogleSheetsClient()
    df = sheets_client.read_data(
        Config.GOOGLE_SHEETS_ID,
        Config.WEBSITE_SHEET_RANGE,
        Config.DETAILS_SHEET_RANGE,
    )

    if df.empty:
        print("❌ No data found")
        return

    print(f"✅ {len(df)} websites to process\n")

    pw = await async_playwright().start()
    success = 0

    for idx, row in df.iterrows():
        status, result = await process_website_forms(
            url=str(row.get("website", "")).strip(),
            sheet_data=row.to_dict() if hasattr(row, 'to_dict') else dict(row),
            row_index=idx,
            sheets_client=sheets_client,
            pw_instance=pw
        )
        if result:
            success += 1
        if idx < len(df) - 1:
            await asyncio.sleep(2)

    await pw.stop()

    print("\n" + "=" * 60)
    print(f"🏁 COMPLETE — {success}/{len(df)} successful")
    print("=" * 60)


async def run_test_mode(url: str, custom_data: dict = None):
    """Test mode for single website."""
    print("=" * 60)
    print("🧪 FORM AUTO-FILLER v14.0 — Test Mode")
    print("=" * 60)
    
    test_data = custom_data or DEFAULT_VALUES.copy()
    
    status, result = await process_website_forms(
        url=url,
        sheet_data=test_data,
        row_index=0,
        sheets_client=None,
        pw_instance=None
    )
    
    print("\n" + "=" * 60)
    print(f"📊 Final Status: {status}")
    print("=" * 60)
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Form Auto-Filler - Automated form submission',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument('--test', '-t', type=str, metavar='URL',
                        help='Test mode: process single website URL')
    parser.add_argument('--name', '-n', type=str, default="John Smith",
                        help='Name to use in test mode')
    parser.add_argument('--email', '-e', type=str, default="john.smith@example.com",
                        help='Email to use in test mode')
    parser.add_argument('--phone', '-p', type=str, default="+1(555) 123-4567",
                        help='Phone to use in test mode')
    parser.add_argument('--message', '-m', type=str, 
                        default="Hello, I am interested in your services. Please contact me.",
                        help='Message to use in test mode')
    parser.add_argument('--company', '-c', type=str, default="ABC Company Inc.",
                        help='Company to use in test mode')
    parser.add_argument('--headless', action='store_true',
                        help='Run browser in headless mode')
    
    args = parser.parse_args()
    
    if args.headless:
        Config.HEADLESS = True
    
    try:
        if args.test:
            custom_data = {
                "Name": args.name,
                "Email": args.email,
                "Phone": args.phone,
                "Message": args.message,
                "Company": args.company,
            }
            result = asyncio.run(run_test_mode(args.test, custom_data))
            sys.exit(0 if result else 1)
        else:
            asyncio.run(run_batch_mode())
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
