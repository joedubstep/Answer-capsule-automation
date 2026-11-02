"""Hand-made keyword lexicon for the Time Ledger classifier.

Generic words only: tools, channels and kinds of work. Never a person's name. Each phrase is tokenized and
stemmed the same way as the action text, and each hit adds LEX_WEIGHT (set in the model) to that label's score.
HR and hiring has no labeled history yet, so the lexicon is the only way it can win.
"""

ROLE = {
    "Personal": ["reels", "reel", "hinge", "snapchat", "spotlight", "instagram", "tiktok", "youtube shorts", "scroll",
                 "scrolling", "nap", "dinner", "lunch", "breakfast", "burgers", "pizza", "cook", "bathroom", "shower",
                 "gym", "workout", "church", "hot chocolate", "coffee", "tea", "snack", "cat", "dog", "oil change",
                 "groceries", "laundry", "errand", "errands", "doctor", "dentist", "haircut", "netflix",
                 "distracted", "trades", "snap"],
    "Sales": ["reactivation", "dial", "dials", "callback", "callbacks", "cold call", "lead call", "leads", "prospect",
              "discovery call", "sales call", "campaign", "price increase", "price raise", "outreach",
              "email campaign", "book a call", "booking link", "call list", "owner", "owners", "lead"],
    "Offer work": ["offer doc", "offer", "bonus", "bonuses", "guarantee", "metaphor", "metaphors", "value enhancer",
                   "value enhancers", "value equation", "pillar", "pillars", "timeline", "agreement", "low ticket",
                   "tier", "pricing", "onboarding doc", "grandfather", "guarantee conditions"],
    "Marketing": ["ad", "ads", "vsl", "website", "x profile", "profile picture", "brand", "landing page", "proof",
                  "testimonial", "linkedin", "instagram story", "headline", "cta"],
    "Client delivery": ["client", "clients", "agc", "splendor", "bland", "bland agent", "business profile",
                        "open beds", "gbp", "meta form", "crm stages", "snapshot", "partner", "partners", "tour",
                        "tours", "visibility", "reddit"],
    "CTO": ["claude", "prompt", "chat", "chats", "skill", "wispr", "setup", "tool", "tools", "routine", "dashboard",
            "artifact", "notion", "wifi", "sidebar", "codex", "fable", "ollama", "github", "api", "effort",
            "compact", "context", "mcp", "repo"],
    "Business development": ["data sale", "data seller", "data selling", "simpleclosure", "simple closure",
                             "polyshares", "polly shares", "mercor", "labelbox", "prism", "datavendor",
                             "data vendor", "quote", "traces", "codebase", "code base", "buyer"],
    "Admin": ["email", "emails", "check email", "inbox", "calendar", "phone", "spam", "gmail", "account",
              "google account", "workspace", "forwarding", "portal", "reschedule", "one on one"],
    "Billing and finance": ["mercury", "bank", "invoice", "invoices", "payment", "payments", "stripe", "cpa", "cpas",
                            "tax", "taxes", "financing", "bill", "bills", "refund", "expense", "expenses"],
    "HR and hiring": ["hire", "hiring", "interview", "candidate", "candidates", "job post", "recruit", "recruiting",
                      "contractor", "virtual assistant", "applicant", "applicants", "team member", "new hire"],
    "CEO": ["plan", "planning", "todo", "notebook", "yc", "application", "learn", "learning", "learnings",
            "internalize", "book", "video", "videos", "coaching", "coach", "mastermind", "strategy",
            "massive action plan", "investor", "ideas", "priorities"],
}

KIND = {
    "Distraction": ["reels", "hinge", "snapchat", "spotlight", "instagram", "tiktok", "scroll", "distracted",
                    "facebook reels", "youtube shorts"],
    "Personal": ["dinner", "lunch", "breakfast", "nap", "bathroom", "shower", "gym", "cook", "burgers", "pizza",
                 "cat", "dog", "church", "hot chocolate", "coffee", "tea", "snack", "groceries", "laundry", "errand",
                 "errands", "doctor", "dentist", "haircut"],
    "Learning": ["learn", "learning", "video", "videos", "book", "internalize", "study", "watch", "transcript",
                 "transcription", "takeaways", "coaching", "rewatch"],
    "Planning": ["plan", "planning", "todo", "notebook", "priorities", "massive action plan"],
    "Tools": ["claude", "prompt", "chat", "skill", "dashboard", "setup", "artifact", "routine", "codex", "fable",
              "wispr", "sidebar"],
    "Admin": ["email", "check email", "inbox", "calendar", "phone", "spam", "account", "portal"],
    "Outreach": ["call", "calls", "dial", "reactivation", "campaign", "followup", "lead", "leads", "cold call",
                 "outreach", "price increase"],
    "Offer": ["offer", "bonus", "bonuses", "guarantee", "metaphor", "agreement", "value enhancer", "timeline",
              "pillar"],
    "Data sale": ["data sale", "simpleclosure", "simple closure", "polyshares", "polly shares", "mercor", "labelbox",
                  "prism", "quote", "datavendor", "data vendor", "codebase", "code base"],
    "Client work": ["client", "agc", "splendor", "bland", "meta", "ghl", "business profile", "open beds"],
    "Marketing": ["ad", "ads", "vsl", "profile", "website", "proof", "linkedin"],
    "SOPs": ["sop", "sops"],
    "Fixes": ["fix", "wifi", "broken", "bug"],
    "Selling": ["sales call", "discovery call", "pitch", "close the deal"],
}

AI = {
    "yes": ["claude", "prompt", "chat", "chats", "codex", "chatgpt", "gpt", "fable", "ai", "artifact",
            "skill", "routine", "compact"],
}

# Words that may stay in the shipped model even when the history writes them with a capital letter:
# tools, products, channels, acronyms and generic title words. Anything else written with a capital letter
# mid-sentence is treated as a possible person name and left out of the model.
ALLOW_CAPITALIZED = set("""
claude notion ghl gohighlevel meta google gmail facebook instagram hinge snapchat spotlight reels reddit x yc
bland fathom wispr flow stripe mercury discord codex fable chatgpt linkedin twilio vercel github ollama clicky muse
sop sops vsl kpi ai pdf crm cta gif hq fbf agc splendor surven lead leads suite leadsuite simpleclosure polyshares
mercor labelbox prism datavendor profile list ads sell offers code documents save senior living business voice
workspace school startup mastery occupancy os cpas traces i s p m k b am pm nov january february saturday
wednesday monday tuesday thursday friday sunday t1 p1 p2 p3 p4 p5 p6 p7 p8 p9 p10 p11 p12 p13
""".split())
