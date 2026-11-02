"""Florida: AHCA assisted living facilities (FloridaHealthFinder facility search, export to Excel).

FloridaHealthFinder refuses an export it calls too large and asks for a narrower search (seen in search snippets
11/2; the site itself was unreachable from the build session). So the build takes a folder of county or area
exports; overlapping files are fine, each home counts once.

Why Florida first: Florida has about 3,000 licensed assisted living facilities and the campaign holds only 230 of
them (built by hand 9/28, only homes whose website showed an email). The AHCA data carries the licensed beds, the
administrator's name and often the home's website, so the website and email finder have something to start from.
Existing Florida ids end with the AHCA FILE number (8 digits), so this module keys on the file number when the
export has it, which makes the dedupe against the 230 exact.
"""
import re

from .base import Source

SPECIALTY = {"ecc": "extended congregate care", "lns": "limited nursing services", "lmh": "limited mental health"}


class Florida(Source):
    code = "fl"
    state = "FL"
    title = "Florida AHCA assisted living facilities"
    agency = "FL AHCA FloridaHealthFinder facility search export"
    page_url = "https://quality.healthfinder.fl.gov/Facility-Search"
    download_url = ""
    link_words = ("assisted", "alf", "export", "excel", "csv")
    how_to = ("Open https://quality.healthfinder.fl.gov/Facility-Search, choose Provider Type 'Assisted Living "
              "Facility', search statewide, then use 'Export to Excel'. If the site says the result is too large "
              "to download, search one county (or one AHCA area) at a time and export each one into the same "
              "empty folder. Pass the file, or the folder, with --file.")
    aliases = {
        "license": ["File Number", "FileNumber", "File No", "File #", "AHCA File Number"],
        "license_no": ["License Number", "LicenseNumber", "License #", "License No"],
        "name": ["Name", "Facility Name", "Provider Name", "FacilityName"],
        "address": ["Street Address", "StreetAddress", "Address"],
        "city": ["Street City", "City", "StreetCity"],
        "zip": ["Street Zip", "Zip", "Zip Code", "StreetZip"],
        "county": ["Street County", "County", "StreetCounty"],
        "phone": ["Phone Number", "PhoneNumber", "Phone"],
        "beds": ["Licensed Beds", "BedCapacity", "Bed Capacity", "Beds", "Total Beds", "Capacity"],
        "administrator": ["Administrator", "Administrator Name", "AdministratorName"],
        "ceo": ["CEO", "Chief Executive Officer"],
        "type": ["Provider Type", "ProviderType", "Facility Type", "License Type"],
        "status": ["License Status", "LicenseStatus", "Status"],
        "website": ["Website", "Web Site", "WebSite", "Web Address", "URL"],
        "licensee": ["Owner", "Licensee", "Owner Name", "Licensee Name"],
        "memory": ["Specialty Licenses", "Specialty License", "Licenses", "Specialty", "Alzheimer"],
        "profile_id": ["LID", "Profile ID", "ProfileID"],
    }

    def include_type(self, type_text):
        t = (type_text or "").lower()
        if not t or "assisted living" in t or t.strip() in ("alf",):
            return True, ""
        return False, f"not assisted living ({type_text})"

    def active(self, status_text):
        s = (status_text or "").strip().lower()
        if s and not re.search(r"licensed|active|in service|open|current|renew|provisional|conditional", s):
            return False, f"license not active ({status_text})"
        return super().active(status_text)

    def care_label(self, rec):
        extra = rec.get("memory", "") or ""
        low = extra.lower()
        parts = ["assisted living facility"]
        if re.search(r"alzheimer|dementia|memory", low):
            parts.append("memory care")
        for k, v in SPECIALTY.items():
            if re.search(rf"\b{k}\b", low):
                parts.append(v)
        return ", ".join(parts)

    def flags(self, rec):
        lic = rec.get("license_no") or "not listed"
        return [f"FL assisted living facility (AHCA license {lic}, file {rec.get('license') or 'not listed'})",
                "no public census for FL"]


SOURCE = Florida()
