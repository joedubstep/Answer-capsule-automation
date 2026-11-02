"""North Carolina: DHSR adult care homes (NC's assisted living license), from the DHSR reports page.

Why North Carolina: none of its homes are in the campaign yet, NC adult care homes are licensed at 7 beds and up
with many at 40 to 120, and DHSR publishes one statewide "Adult Care Home Listing" (XLSX and PDF, plus
comma-delimited text with a header file) on https://info.ncdhhs.gov/dhsr/reports.htm. Family care homes (2 to 6
beds) are a separate license and never reach the 40-bed bar. The whole state is Eastern time.
"""
import re

from .base import Source


class NorthCarolina(Source):
    code = "nc"
    state = "NC"
    title = "North Carolina DHSR adult care homes"
    agency = "NC DHSR Adult Care Home Listing"
    page_url = "https://info.ncdhhs.gov/dhsr/reports.htm"
    download_url = ""
    link_words = ("adult care", "ach", "aclist", "acl")
    how_to = ("Open https://info.ncdhhs.gov/dhsr/reports.htm and download 'Adult Care Home Listing' as XLSX "
              "(or the comma-delimited text file). Pass it with --file. `run find-download --state nc` prints "
              "the current link when the page loads.")
    aliases = {
        "license": ["License Number", "License #", "License No", "LicenseNumber", "Lic #", "License", "HAL Number",
                    "Facility ID", "FID"],
        "name": ["Facility Name", "Name", "Facility"],
        "address": ["Facility Address", "Site Address", "Address", "Street Address", "Location Address",
                    "Physical Address", "Address 1"],
        "city": ["Facility City", "Site City", "City"],
        "zip": ["Facility Zip", "Zip", "Zip Code", "ZipCode"],
        "county": ["County", "County Name"],
        "phone": ["Facility Phone", "Phone", "Phone Number", "Telephone"],
        "beds": ["Licensed Beds", "Total Beds", "Beds", "Bed Capacity", "Capacity", "ACH Beds", "Licensed Capacity",
                 "Total Licensed Beds", "Licensed ACH Beds"],
        "administrator": ["Administrator", "Administrator Name", "Admin", "Administrator/Supervisor-in-Charge",
                          "Administrator In Charge"],
        "type": ["Facility Type", "License Type", "Type", "Facility Type Description"],
        "status": ["License Status", "Status"],
        "licensee": ["Licensee", "Licensee Name", "Owner"],
        "memory": ["Special Care Unit Beds", "SCU Beds", "Special Care Unit", "SCU", "Alzheimer Beds",
                   "Special Care Beds"],
    }
    care = "adult care home (assisted living)"

    def include_type(self, type_text):
        t = (type_text or "").lower()
        if not t or "adult care" in t or t.strip() in ("ach", "ach - adult care home"):
            return True, ""
        if "family care" in t:
            return False, f"family care home, not an adult care home ({type_text})"
        return False, f"not an adult care home ({type_text})"

    def care_label(self, rec):
        m = re.search(r"\d+", rec.get("memory", "") or "")
        if m and int(m.group(0)) > 0:
            return f"adult care home (assisted living), memory care ({int(m.group(0))} special care beds)"
        if (rec.get("memory") or "").strip().lower() in ("y", "yes", "true"):
            return "adult care home (assisted living), memory care"
        return self.care

    def flags(self, rec):
        return [f"NC adult care home (DHSR license {rec.get('license') or 'not listed'})",
                "no public census for NC"]


SOURCE = NorthCarolina()
