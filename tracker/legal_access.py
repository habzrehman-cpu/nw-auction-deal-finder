"""Configuration and guarded authentication for auction legal-pack acquisition.

The acquisition layer deliberately does not bypass CAPTCHAs, anti-bot controls,
registration requirements, paywalls, or provider terms. Sources whose published
terms require prior permission for automated access are disabled unless the user
explicitly records that permission in private configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PROVIDER_RULES = {
    "auction_house": {
        "label": "Auction House / Auction Passport",
        "permission_required": True,
        "login_expected": True,
        "reason": "Auction House published terms restrict automated viewing without consent.",
    },
    "allsop": {
        "label": "Allsop",
        "permission_required": True,
        "login_expected": False,
        "reason": "Allsop published terms restrict robots/data-extraction tools without prior written permission.",
    },
    "savills": {
        "label": "Savills Auctions",
        "permission_required": False,
        "login_expected": True,
        "reason": "Savills legal documents are account-gated; authenticated access uses the user's own account and stops at CAPTCHA/anti-bot controls.",
    },
    "eddisons": {
        "label": "BTG Eddisons",
        "permission_required": False,
        "login_expected": True,
        "public_first": True,
        "reason": "Public lot-bound legal files are attempted first; some lots may be account-gated and can use the buyer's own configured credentials.",
    },
    "generic": {
        "label": "Other source",
        "permission_required": False,
        "login_expected": False,
        "reason": "Only directly accessible public legal documents are retrieved.",
    },
}


@dataclass
class ProviderAccess:
    enabled: bool = True
    permission_confirmed: bool = False
    email: str = ""
    password: str = ""
    cookie: str = ""
    login_url: str = ""

    @property
    def has_credentials(self) -> bool:
        return bool(self.cookie or (self.email and self.password))


@dataclass
class LegalAccessConfig:
    auto_enabled: bool = True
    providers: dict[str, ProviderAccess] = field(default_factory=dict)

    def for_provider(self, provider: str) -> ProviderAccess:
        return self.providers.get(provider) or ProviderAccess()


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _mapping_get(mapping, key, default=None):
    try:
        return mapping.get(key, default)
    except Exception:
        return default


def config_from_mapping(mapping) -> LegalAccessConfig:
    """Read legal-source settings from Streamlit Secrets or a dict-like object."""
    root = _mapping_get(mapping, "legal_sources", {}) if mapping is not None else {}
    auto_enabled = _bool(_mapping_get(root, "auto_enabled", os.environ.get("LEGAL_AUTO_ENABLED", "true")), True)
    providers = {}
    for provider in PROVIDER_RULES:
        if provider == "generic":
            continue
        section = _mapping_get(root, provider, {}) or {}
        prefix = f"LEGAL_{provider.upper()}_"
        providers[provider] = ProviderAccess(
            enabled=_bool(_mapping_get(section, "enabled", os.environ.get(prefix + "ENABLED", "true")), True),
            permission_confirmed=_bool(_mapping_get(section, "permission_confirmed", os.environ.get(prefix + "PERMISSION_CONFIRMED", "false")), False),
            email=str(_mapping_get(section, "email", os.environ.get(prefix + "EMAIL", "")) or "").strip(),
            password=str(_mapping_get(section, "password", os.environ.get(prefix + "PASSWORD", "")) or ""),
            cookie=str(_mapping_get(section, "cookie", os.environ.get(prefix + "COOKIE", "")) or "").strip(),
            login_url=str(_mapping_get(section, "login_url", os.environ.get(prefix + "LOGIN_URL", "")) or "").strip(),
        )
    return LegalAccessConfig(auto_enabled=auto_enabled, providers=providers)


def provider_for_lot(lot: dict | None = None, url: str = "") -> str:
    lot = lot or {}
    source = str(lot.get("source") or "").lower()
    probe = f"{source} {url or lot.get('url') or ''}".lower()
    if "auction house" in probe or "auctionhouse.co.uk" in probe or "auction passport" in probe:
        return "auction_house"
    if "allsop" in probe:
        return "allsop"
    if "savills" in probe:
        return "savills"
    if "eddisons" in probe:
        return "eddisons"
    return "generic"


def provider_access_status(config: LegalAccessConfig | None, provider: str) -> dict:
    rule = PROVIDER_RULES.get(provider, PROVIDER_RULES["generic"])
    cfg = (config or LegalAccessConfig()).for_provider(provider)
    if not (config or LegalAccessConfig()).auto_enabled:
        return {"allowed": False, "status": "automation disabled", "provider": provider, "label": rule["label"]}
    if not cfg.enabled:
        return {"allowed": False, "status": "source disabled", "provider": provider, "label": rule["label"]}
    if rule.get("permission_required") and not cfg.permission_confirmed:
        return {
            "allowed": False,
            "status": "provider permission required",
            "provider": provider,
            "label": rule["label"],
            "reason": rule.get("reason"),
        }
    if rule.get("login_expected") and not cfg.has_credentials:
        return {
            "allowed": True,
            "status": (
                "public acquisition enabled; account fallback not configured"
                if rule.get("public_first") else "login credentials not configured"
            ),
            "provider": provider,
            "label": rule["label"],
            "reason": rule.get("reason"),
        }
    return {
        "allowed": True,
        "status": "authenticated automation configured" if cfg.has_credentials else "public auto-download enabled",
        "provider": provider,
        "label": rule["label"],
        "reason": rule.get("reason"),
    }


def _has_captcha(html: str) -> bool:
    probe = (html or "").lower()
    return any(x in probe for x in ("g-recaptcha", "recaptcha", "hcaptcha", "cf-turnstile", "captcha"))


def _password_form(soup: BeautifulSoup):
    for form in soup.find_all("form"):
        if form.find("input", attrs={"type": re.compile("password", re.I)}):
            return form
    return None


def login_from_page(session: requests.Session, page_url: str, email: str, password: str) -> tuple[bool, str]:
    """Attempt a conventional HTML-form login without bypassing anti-bot controls.

    Hidden CSRF inputs are preserved. If a CAPTCHA/turnstile is present, authentication
    stops and the caller is told to use manual/browser access instead.
    """
    first = session.get(page_url, timeout=30, allow_redirects=True)
    first.raise_for_status()
    if _has_captcha(first.text):
        return False, "CAPTCHA/anti-bot challenge detected; manual browser access required"
    soup = BeautifulSoup(first.text, "html.parser")
    form = _password_form(soup)
    if not form:
        return True, "no login form present"

    password_input = form.find("input", attrs={"type": re.compile("password", re.I)})
    candidates = form.find_all("input")
    user_input = None
    for inp in candidates:
        typ = str(inp.get("type") or "").lower()
        name = str(inp.get("name") or "")
        if typ == "email" or re.search(r"email|username|user|login", name, re.I):
            user_input = inp
            break
    if not user_input or not password_input or not user_input.get("name") or not password_input.get("name"):
        return False, "login form could not be safely identified"

    payload = {}
    for inp in candidates:
        name = inp.get("name")
        if not name:
            continue
        typ = str(inp.get("type") or "").lower()
        if typ in {"hidden", "submit"} and inp.get("value") is not None:
            payload[name] = inp.get("value")
    payload[user_input.get("name")] = email
    payload[password_input.get("name")] = password
    action = urljoin(first.url, form.get("action") or first.url)
    method = str(form.get("method") or "post").lower()
    if method == "get":
        logged = session.get(action, params=payload, timeout=30, allow_redirects=True)
    else:
        logged = session.post(action, data=payload, timeout=30, allow_redirects=True)
    logged.raise_for_status()
    if _has_captcha(logged.text):
        return False, "CAPTCHA/anti-bot challenge detected after login attempt"
    low = " ".join(BeautifulSoup(logged.text, "html.parser").get_text(" ", strip=True).lower().split())[:6000]
    if any(x in low for x in ("incorrect password", "invalid password", "login failed", "invalid username", "incorrect username")):
        return False, "login was rejected by the provider"
    return True, "login form submitted"


def prepare_authenticated_session(session: requests.Session, page_url: str, provider: str,
                                  config: LegalAccessConfig | None) -> tuple[bool, str]:
    """Apply configured credentials/cookie to a session for a permitted provider."""
    cfg = (config or LegalAccessConfig()).for_provider(provider)
    rule = PROVIDER_RULES.get(provider, PROVIDER_RULES["generic"])
    if rule.get("permission_required") and not cfg.permission_confirmed:
        return False, "provider permission required for automated access"
    if cfg.cookie:
        session.headers.update({"Cookie": cfg.cookie})
        return True, "configured authenticated session cookie applied"
    if not (cfg.email and cfg.password):
        return False, "login credentials not configured"
    login_url = cfg.login_url or page_url
    return login_from_page(session, login_url, cfg.email, cfg.password)
