"""What every state source module declares. A new state is one small file: its page, its column aliases, which
license types count as assisted living, and how it labels care and time zone. The pipeline does the rest."""
import re

from .. import common

# Field -> header names seen across state downloads. A module adds its own names in front of these.
BASE_ALIASES = {
    "license": ["License Number", "License #", "License No", "License No.", "LicenseNumber", "License", "Lic #",
                "Lic No", "Facility License Number", "License ID", "Facility ID", "Provider Number"],
    "name": ["Facility Name", "Name", "Provider Name", "FacilityName", "Facility", "Provider", "Name of Facility",
             "Business Name", "DBA"],
    "address": ["Street Address", "Address", "StreetAddress", "Address Line 1", "Address1", "Street",
                "Physical Address", "Site Address", "Location Address", "Facility Address"],
    "city": ["City", "Street City", "StreetCity", "Site City", "Physical City", "Facility City"],
    "zip": ["Zip", "Zip Code", "ZipCode", "Street Zip", "Postal Code", "Site Zip", "Facility Zip"],
    "county": ["County", "Street County", "County Name", "Site County"],
    "phone": ["Phone", "Phone Number", "PhoneNumber", "Telephone", "Facility Phone", "Facility Phone Number",
              "Business Phone", "Telephone Number"],
    "beds": ["Licensed Beds", "Beds", "Bed Capacity", "BedCapacity", "Total Beds", "Capacity", "Licensed Capacity",
             "Total Licensed Beds", "Total Capacity", "Number of Beds", "Bed Count"],
    "administrator": ["Administrator", "Administrator Name", "AdministratorName", "Admin", "Admin Name",
                      "Facility Administrator", "Administrator Full Name"],
    "type": ["Provider Type", "Facility Type", "License Type", "ProviderType", "Type", "Program Type",
             "Facility Type Description"],
    "status": ["License Status", "Status", "LicenseStatus", "Facility Status", "Operating Status"],
    "email": ["Email", "Email Address", "E-mail", "E-mail Address", "Facility Email", "EmailAddress"],
    "website": ["Website", "Web Site", "Web Address", "URL", "WebSite", "Web"],
    "licensee": ["Licensee", "Owner", "Owner Name", "Licensee Name", "Operator"],
    "memory": ["Special Care Unit Beds", "SCU Beds", "Special Care Unit", "Specialty Licenses", "Specialty",
               "Alzheimer", "Memory Care"],
}
INACTIVE = re.compile(r"closed|inactive|expired|revoked|surrender|suspend|pending|withdrawn|denied|terminat|"
                      r"not open|delinquent|void|cancel", re.I)


class Source:
    code = ""            # 'fl'
    state = ""           # 'FL'
    title = ""           # 'Florida AHCA assisted living facilities'
    agency = ""          # 'FL AHCA FloridaHealthFinder'
    page_url = ""        # where a person downloads the list
    download_url = ""    # a direct file link when one is known to work; else '' (use --file or find-download)
    link_words = ()      # words that mark the right file on page_url (find-download)
    how_to = ""          # plain steps to get the file by hand
    aliases = {}         # field -> extra header names, tried before BASE_ALIASES
    care = "assisted living facility"
    beds_word = "beds"
    admin_order = "first_last"  # 'last_first' when the list prints 'EXAMPLE PAT' with no comma (see run inspect)
    required = ("name", "beds")

    def all_aliases(self):
        out = {}
        for k in set(BASE_ALIASES) | set(self.aliases):
            out[k] = list(dict.fromkeys(list(self.aliases.get(k, [])) + BASE_ALIASES.get(k, [])))
        return out

    # ---- per-state judgment, overridable ----
    def include_type(self, type_text):
        """(True, '') when the license type is assisted living; else (False, reason)."""
        return True, ""

    def active(self, status_text):
        if status_text and INACTIVE.search(status_text):
            return False, f"license not active ({status_text})"
        return True, ""

    def care_label(self, rec):
        return self.care

    def tz(self, rec):
        return common.tz_for(self.state, rec.get("county", ""), rec.get("city", ""))

    def license_of(self, get):
        return get("license")

    def phone_source(self, header):
        return f"{self.agency} ({self.page_url}), column '{header}'"

    def website_source(self):
        return "state license list"

    def email_source(self):
        return f"{self.state} state facility list"

    def flags(self, rec):
        return [f"{self.state} {self.care} ({self.agency} license {rec.get('license') or 'not listed'})"]
