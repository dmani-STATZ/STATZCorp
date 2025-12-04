import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


PHONE_REGEX = re.compile(r"\+?\d[\d\s\-\(\)]{9,}")
EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
ZIP_REGEX = re.compile(r"\b\d{5}(?:-\d{4})?\b")
ADDRESS_REGEX = re.compile(r"\d{1,5}\s+[\w\s\.\-]+,\s*[\w\s\.\-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?")
CAGE_REGEX = re.compile(r"\b[A-Z0-9]{5}\b")


def scrape_supplier_site(url: str) -> dict:
    """
    Fetches the given URL (and a handful of contact/about/company pages) and attempts to extract:
    - logo_url
    - primary_phone
    - primary_email
    - address (string)

    Returns a dict with any found keys. Safe: returns {} on failure.
    """
    headers = {"User-Agent": "STATZBot/1.3 (+https://statzcorp.com)"}

    def fetch(url_to_fetch: str) -> str:
        try:
            resp = requests.get(url_to_fetch, timeout=5, headers=headers)
            resp.raise_for_status()
            return resp.text
        except Exception:
            return ""

    def abs_url(base: str, val: str) -> str | None:
        if not val:
            return None
        return urljoin(base, val.strip())

    def clean_phone(val: str) -> str | None:
        if not val:
            return None
        cleaned = re.sub(r"[^\d\+]", "", val)
        return cleaned or val

    def add_value(field: str, value):
        if not value:
            return
        if field not in suggestions:
            suggestions[field] = set()
        suggestions[field].add(value)

    def extract_from_soup(soup: BeautifulSoup, base_url: str, suggestions: dict):
        # Footer-first scrape
        footer = soup.find("footer")
        if footer:
            footer_text = footer.get_text(" ", strip=True)
            phone_match = PHONE_REGEX.search(footer_text)
            email_match = EMAIL_REGEX.search(footer_text)
            address_match = ADDRESS_REGEX.search(footer_text) or ZIP_REGEX.search(footer_text)
            cage_match = CAGE_REGEX.search(footer_text)
            if phone_match:
                add_value("primary_phone", clean_phone(phone_match.group(0)))
            if email_match:
                add_value("primary_email", email_match.group(0))
            if address_match:
                add_value("address", address_match.group(0) if hasattr(address_match, "group") else footer_text)
            if cage_match:
                add_value("cage_code", cage_match.group(0))
            for link in footer.select('a[href^="tel:"]'):
                phone_text = link.get_text(strip=True) or link.get("href", "").replace("tel:", "")
                add_value("primary_phone", clean_phone(phone_text))

        # JSON-LD
        try:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                except Exception:
                    continue
                entries = data if isinstance(data, list) else [data]
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    atype = entry.get("@type")
                    types = atype if isinstance(atype, list) else [atype]
                    if any(t in ["Organization", "LocalBusiness"] for t in types):
                        add_value("logo_url", abs_url(base_url, entry.get("logo")))
                        add_value("primary_phone", entry.get("telephone"))
                        add_value("primary_email", entry.get("email"))
                        addr = entry.get("address")
                        if isinstance(addr, dict):
                            parts = [
                                addr.get("streetAddress"),
                                addr.get("addressLocality"),
                                addr.get("addressRegion"),
                                addr.get("postalCode"),
                                addr.get("addressCountry"),
                            ]
                            addr_str = ", ".join([p for p in parts if p])
                            add_value("address", addr_str if addr_str else None)
                        elif isinstance(addr, str):
                            add_value("address", addr)
                        contact_points = entry.get("contactPoint") or entry.get("contactPoints")
                        if isinstance(contact_points, list):
                            for cp in contact_points:
                                if not isinstance(cp, dict):
                                    continue
                                add_value("primary_phone", cp.get("telephone"))
                                add_value("primary_email", cp.get("email"))
                        if suggestions.get("address") is None and isinstance(entry.get("address"), str):
                            add_value("address", entry.get("address"))
                        break
        except Exception:
            pass

        # Microdata itemprop
        if not suggestions.get("primary_phone"):
            tel_el = soup.find(attrs={"itemprop": "telephone"})
            if tel_el:
                add_value("primary_phone", clean_phone(tel_el.get_text(" ", strip=True)))
        if not suggestions.get("primary_email"):
            email_el = soup.find(attrs={"itemprop": "email"})
            if email_el:
                add_value("primary_email", email_el.get_text(" ", strip=True))
        if not suggestions.get("address"):
            addr_el = soup.find(attrs={"itemprop": "address"})
            if addr_el:
                add_value("address", addr_el.get_text(" ", strip=True))

        # Logos
        if not suggestions.get("logo_url"):
            og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
            if og_image and og_image.get("content"):
                add_value("logo_url", abs_url(base_url, og_image.get("content")))
        if not suggestions.get("logo_url"):
            icon = soup.find("link", rel=lambda v: v and "icon" in v.lower())
            if icon and icon.get("href"):
                add_value("logo_url", abs_url(base_url, icon.get("href")))
        if not suggestions.get("logo_url"):
            logo_img = soup.find("img", class_=re.compile("logo", re.I)) or soup.find("img", id=re.compile("logo", re.I))
            if logo_img and logo_img.get("src"):
                add_value("logo_url", abs_url(base_url, logo_img.get("src")))
        if not suggestions.get("logo_url"):
            header_logo = soup.select_one("header img")
            if header_logo and header_logo.get("src"):
                add_value("logo_url", abs_url(base_url, header_logo.get("src")))
        if not suggestions.get("logo_url"):
            alt_logo = soup.find("img", alt=re.compile("logo", re.I))
            if alt_logo and alt_logo.get("src"):
                add_value("logo_url", abs_url(base_url, alt_logo.get("src")))
        if not suggestions.get("logo_url"):
            logo_candidates = soup.select("header img, footer img")
            for img in logo_candidates:
                src = img.get("src")
                if src and any(k in src.lower() for k in ["logo", "header", "brand"]):
                    add_value("logo_url", abs_url(base_url, src))
                    break

        # Address fallback
        if not suggestions.get("address"):
            addr_tag = soup.find("address")
            if addr_tag:
                addr_text = addr_tag.get_text(" ", strip=True)
                add_value("address", addr_text)
            else:
                possible = soup.find_all(class_=re.compile(r"(address|location|contact)", re.I))
                for el in possible:
                    text = el.get_text(" ", strip=True)
                    if re.search(r"\b\d{5}(?:-\d{4})?\b", text):
                        add_value("address", text)
                        break

        # Phone/email/address/CAGE regex fallback in body text
        body_text = soup.get_text(" ", strip=True)
        if not suggestions.get("primary_phone"):
            phone_match = PHONE_REGEX.search(body_text)
            if phone_match:
                add_value("primary_phone", clean_phone(phone_match.group(0)))
        if not suggestions.get("primary_email"):
            email_match = EMAIL_REGEX.search(body_text)
            if email_match:
                add_value("primary_email", email_match.group(0))
        if not suggestions.get("address"):
            address_match = ADDRESS_REGEX.search(body_text) or ZIP_REGEX.search(body_text)
            if address_match:
                add_value("address", address_match.group(0))
        if not suggestions.get("cage_code"):
            cage_match = CAGE_REGEX.search(body_text)
            if cage_match:
                add_value("cage_code", cage_match.group(0))

    # Crawl main page and targeted in-domain pages
    domain = urlparse(url).netloc
    seen = set()
    queue = [url] + [urljoin(url, p) for p in ["/contact", "/contact-us", "/about", "/company"]]
    suggestions: dict = {}

    while queue and len(seen) < 3:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        html = fetch(current)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        extract_from_soup(soup, current, suggestions)
        if len(seen) == 1:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(" ", strip=True).lower()
                if any(key in href.lower() for key in ["contact", "about"]) or any(
                    key in text for key in ["contact", "about"]
                ):
                    candidate = urljoin(current, href)
                    if urlparse(candidate).netloc == domain and candidate not in seen:
                        queue.append(candidate)
                if len(queue) > 3:
                    break
        print(f"[SCRAPER] Crawled URL: {current}")
        print(f"[SCRAPER] Found: phone={suggestions.get('primary_phone')}, email={suggestions.get('primary_email')}, address={suggestions.get('address')}, logo={suggestions.get('logo_url')}, cage={suggestions.get('cage_code')}")

    # convert sets to lists and drop empties
    return {k: list(v) for k, v in suggestions.items() if v}
