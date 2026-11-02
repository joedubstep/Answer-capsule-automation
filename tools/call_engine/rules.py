"""Pattern tables for the Call Engine. rubric.md explains every id used here; keep the two in sync
(tests/test_rules.py checks that each id below appears in rubric.md).

Everything here is matched case-insensitively against single sentences of a Fathom transcript.
A regex here finds EVIDENCE with a timestamp. The model still makes the call on the scorecard.

  FLAGS        things Joey said that the rubric bans
  MOVES        call steps and questions to look for (timeline asked, deposit asked, next call booked, ...)
  OBJECTIONS   prospect lines that look like an objection
  PROMISE      Joey's "I'll send you ..." lines, which become owed items
  RUBRIC_ITEMS the scorecard rows the review must fill
  REMINDERS    watch-note reminders for call prep, picked by signals
  EXPECT       objections to expect on a call, picked by signals
"""
import re

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# The host is Joey. These first names only help find his speaker label in a transcript and strip him
# out of calendar titles ("Joey x Pat"). Pass --host to override.
HOST_FIRST_NAMES = ("joey", "joseph")

FLAGS = [
    {
        "id": "good_time_ask", "severity": "high",
        "label": "Asked if it is a good or bad time",
        "fix": "Never ask. Open with the frame and the first question.",
        "patterns": [
            r"\b(?:is|was)\s+(?:now|this|it|today)\s+(?:still\s+)?(?:a\s+)?(?:bad|good|better|okay|ok|convenient|fine)\s+time\b",
            r"\b(?:bad|good|convenient)\s+time\s+(?:to\s+(?:talk|chat)|for\s+(?:you|a\s+(?:call|chat)))\b",
            r"\bcatch(?:ing)?\s+you\s+at\s+a\s+(?:bad|good)\s+time\b",
            r"\bdo\s+you\s+(?:still\s+)?have\s+(?:a\s+(?:few|couple)\s+(?:of\s+)?(?:minutes|mins)|a\s+minute)\b",
        ],
    },
    {
        "id": "cancel_placement", "severity": "high",
        "label": "Told them to drop their placement agents",
        "fix": "Never knock the agents. Keep them, and stop being only dependent on them.",
        "patterns": [
            r"\b(?:cancel|drop|stop\s+using|get\s+rid\s+of|fire|ditch|quit)\s+(?:your\s+|the\s+|those\s+)?(?:placement|referral)\s+"
            r"(?:agen(?:ts?|cy|cies)|services?|companies)\b",
            r"\b(?:won't|will\s+not|don't|do\s+not)\s+need\s+(?:your\s+|the\s+|any\s+)?(?:placement|referral)\s+agen(?:ts?|cy|cies)\b",
        ],
    },
    {
        "id": "banned_name", "severity": "medium",
        "label": "Banned word or old product name",
        "fix": "Never 'death spiral'. It is the Five-Minute Front Desk, never 'virtual front desk'.",
        "patterns": [r"\bdeath[\s-]+spiral\b", r"\bvirtual[\s-]+front[\s-]+desk\b", r"\bcharge[\s-]?backs?\b"],
    },
    {
        "id": "patients", "severity": "medium",
        "label": "Said patients",
        "fix": "Say residents.",
        "patterns": [r"\bpatients?\b"],
    },
    {
        "id": "leads_for_families", "severity": "low",
        "label": "Said leads about families",
        "fix": "Say families.",
        "patterns": [r"\bleads\b(?!\s+(?:to|into)\b)"],
    },
    {
        "id": "financing", "severity": "medium",
        "label": "Financing or a payment plan came up",
        "fix": "Only after the break-even screen. A home below break-even is a bad client; do not finance it.",
        "patterns": [r"\bfinanc(?:e|ing)\b", r"\bpayment\s+plan\b"],
    },
]

MOVES = [
    {"id": "agenda", "label": "Set the frame for the call", "speaker": "host", "patterns": [
        r"\brun\s+you\s+through\b", r"\bhow\s+I\s+(?:usually\s+)?(?:handle|run|do)\s+these\b", r"\bagenda\b",
        r"\bgood\s+use\s+of\s+your\s+time\b",
        r"\bask\s+you\s+(?:a\s+)?(?:bunch\s+of|few|couple(?:\s+of)?)\s+questions\b"]},
    {"id": "discovery_open", "label": "First discovery question", "speaker": "host", "patterns": [
        r"\btell\s+me\s+(?:a\s+)?(?:little\s+)?(?:bit\s+)?about\b", r"\bwalk\s+me\s+through\b",
        r"\bwhat\s+(?:made|got)\s+you\b", r"\bwhat's\s+going\s+on\b",
        r"\bhow\s+many\s+(?:beds|rooms|residents|homes)\b", r"\bwhat\s+(?:kind|type)\s+of\s+(?:home|community|facility)\b"]},
    {"id": "problem_probe", "label": "Made them describe the problem", "speaker": "host", "patterns": [
        r"\bwhat\s+(?:are\s+you|have\s+you\s+been)\s+doing\s+to\s+(?:get|fill)\b", r"\bwhat\s+does\s+that\s+look\s+like\b",
        r"\bhow\s+do\s+you\s+mean\b", r"\bwhat\s+do\s+you\s+mean\b", r"\btell\s+me\s+more\b",
        r"\bwhy\s+is\s+that\s+(?:an\s+issue|a\s+problem)\b", r"\bwhat's\s+(?:the\s+)?(?:hardest|biggest)\b",
        r"\bwhen\s+you\s+say\b"]},
    {"id": "timeline", "label": "Timeline question (how long)", "speaker": "host", "patterns": [
        r"\bhow\s+long\b", r"\bsince\s+when\b", r"\bwhen\s+did\s+(?:this|that|it|you)\s+(?:start|begin|first)\b",
        r"\bhow\s+many\s+(?:months|weeks|years)\b", r"\ba\s+couple\s+(?:of\s+)?(?:months|years)\s+or\b"]},
    {"id": "tried", "label": "What have you tried", "speaker": "host", "patterns": [
        r"\bwhat\s+(?:else\s+)?(?:have|has|did)\s+(?:you|y'all|they)(?:\s+guys)?\s+(?:\w+\s+){0,2}(?:tried|done|try|do)\b",
        r"\btried\s+(?:anything|any\s+\w+)\b", r"\bwhat\s+else\b"]},
    {"id": "cost", "label": "What is it costing you", "speaker": "host", "patterns": [
        r"\bcost(?:ing)?\s+you\b", r"\bwhat\s+(?:is|does|would|has)\s+(?:that|this|it)\s+(?:cost|costing|mean)\b",
        r"\b(?:empty|open)\s+(?:bed|room)s?\s+(?:cost|costs|is\s+costing)\b",
        r"\bhow\s+much\s+(?:money\s+)?(?:are\s+you|is\s+that)\s+(?:losing|leaving)\b"]},
    {"id": "why_now", "label": "Why now", "speaker": "host", "patterns": [
        r"\bwhy\s+now\b", r"\bwhat\s+made\s+you\s+(?:book|reach|look|want|click|decide)\b",
        r"\bwhy\s+(?:did\s+you|are\s+you)\s+(?:book|look|reach)\w*\b"]},
    {"id": "goal", "label": "Their goal", "speaker": "host", "patterns": [
        r"\bwhat\s+(?:kind\s+of\s+(?:help|results?)\s+)?(?:are|would)\s+(?:you|y'all)(?:\s+guys)?(?:\s+be)?\s+(?:\w+\s+){0,2}looking\s+(?:for|to)\b",
        r"\bwhat\s+(?:do|would)\s+you\s+(?:want|like\s+to\s+see)\b", r"\bwhere\s+do\s+you\s+want\s+to\s+be\b",
        r"\bhow\s+many\s+(?:beds|residents|move[\s-]?ins)\s+do\s+you\s+(?:want|need)\b"]},
    {"id": "humble_vs_actual", "label": "Humble goal or actual goal", "speaker": "host", "patterns": [
        r"\bhumble\s+goal\b", r"\bactual\s+goal\b"]},
    {"id": "commitment", "label": "Asked for a commitment to change", "speaker": "host", "patterns": [
        r"\b(?:are|is)\s+(?:you|y'all|that\s+something\s+you)(?:\s+guys)?\s+(?:\w+\s*,?\s+){0,4}(?:looking|ready|willing|wanting|committed)\s+"
        r"to\s+(?:get|make|change|fix|implement|solve|start|do|move)\b",
        r"\bcommit(?:ment)?\s+to\s+(?:a\s+)?(?:change|making)\b", r"\bsooner\s+(?:rather\s+)?than\s+later\b",
        r"\blooking\s+around\s+or\b", r"\bjust\s+(?:looking|browsing)\s+or\b",
        r"\bon\s+a\s+scale\s+of\s+(?:1|one)\s+to\s+(?:10|ten)\b", r"\bunless\s+I'm\s+missing\s+something\b"]},
    {"id": "decision_maker", "label": "Asked who else decides", "speaker": "host", "patterns": [
        r"\b(?:anyone|anybody|who)\s+else\b", r"\bpartners?\b", r"\b(?:wife|husband|spouse)\b",
        r"\bdecision[\s-]?mak(?:er|ers|ing)\b", r"\bin\s+the\s+know\b"]},
    {"id": "capacity", "label": "Capacity screen (could you staff more)", "speaker": "host", "patterns": [
        r"\bstaff(?:ed|ing)?\b", r"\bcaregivers?\b", r"\bcould\s+you\s+(?:handle|take|staff)\b", r"\bcapacity\b",
        r"\bif\s+(?:\w+\s+)?more\s+families\b"]},
    {"id": "empty_beds", "label": "Asked how many beds are empty", "speaker": "host", "patterns": [
        r"\bhow\s+many\s+(?:\w+\s+){0,2}(?:beds|rooms|openings|vacanc\w+|residents)\b",
        r"\b(?:beds|rooms)\s+(?:\w+\s+)?(?:open|empty|available)\b", r"\bcensus\b", r"\boccupan\w+\b"]},
    {"id": "rent", "label": "Asked their monthly rate", "speaker": "host", "patterns": [
        r"\bhow\s+much\s+(?:do|are|does)\s+(?:you|y'all)(?:\s+guys)?\s+(?:usually\s+)?(?:charge|go\s+for|get|bill)\b",
        r"\bwhat(?:'s|\s+is)\s+(?:your\s+)?(?:monthly\s+)?(?:rent|rate)\b", r"\bper\s+(?:bed|room)\b"]},
    {"id": "placement", "label": "Placement agents came up", "speaker": "host", "patterns": [
        r"\bplacement\b", r"\breferral\s+agen\w+\b"]},
    {"id": "screen_share", "label": "Shared the screen (pitch starts)", "speaker": "host", "patterns": [
        r"\bshare\s+my\s+screen\b", r"\bsee\s+my\s+screen\b", r"\bscreen\s?share\b"]},
    {"id": "guarantee", "label": "Stated the guarantee", "speaker": "host", "patterns": [r"\bguarantee\w*\b"]},
    {"id": "urgency", "label": "Stated the deadline (urgency)", "speaker": "host", "patterns": [
        r"\bprice\w*\s+(?:goes|go|is\s+going\s+to\s+go|will\s+go)\s+up\b", r"\b(?:price\s+)?increase\b",
        r"\boriginal\s+price\b", r"\bdeadline\b", r"\bends\s+(?:on\s+)?(?:nov\w*|dec\w*|\w+day|the\s+\d+)\b", r"\bcohort\b"]},
    {"id": "scarcity", "label": "Stated scarcity", "speaker": "host", "patterns": [
        r"\b(?:spots?|openings)\s+left\b", r"\bcapped\b", r"\bone\s+(?:community|home)\s+per\s+(?:city|area|market)\b",
        r"\bonly\s+(?:take|work\s+with)\s+\d+\b", r"\blimited\s+(?:spots|number)\b"]},
    {"id": "deposit", "label": "Asked for the refundable deposit", "speaker": "host", "patterns": [
        r"\bdeposit\b", r"\brefundable\b", r"\bhold\s+(?:your|the)\s+spot\b"]},
    {"id": "payment_close", "label": "Asked for payment or the signature", "speaker": "host", "patterns": [
        r"\b(?:payment|stripe)\s+link\b", r"\bcard\s+(?:number|details|info)\b",
        r"\bpay\s+(?:today|now|in\s+full|upfront|up\s+front)\b", r"\bpaid\s+in\s+full\b",
        r"\bsplit\s+(?:it|the\s+payment|payments)\b", r"\bget\s+you\s+started\b",
        r"\bsend\s+(?:you\s+)?the\s+(?:agreement|contract|invoice)\b", r"\bsign\s+(?:the\s+)?(?:agreement|contract)\b",
        r"\bin\s+the\s+chat\b"]},
    {"id": "tie_down", "label": "Tie-down (make sense? ya?)", "speaker": "host", "patterns": [
        r"\b(?:does\s+that|that|it)\s+(?:kind\s+of\s+)?make\s+(?:any\s+)?sense\b", r"\bmake\s+any\s+sense\b",
        r"\bfair\s*\?", r",\s*(?:ya|yeah|right)\s*\?"]},
    {"id": "any_questions", "label": "Asked 'any questions?'", "speaker": "host", "patterns": [r"\bany\s+questions\b"]},
    {"id": "next_step", "label": "Booked or proposed the next call", "speaker": "host", "patterns": [
        r"\b(?:book|schedule|set\s+up|put|lock\s+in|grab)\s+(?:a|the|another|our|your|a\s+quick)\s+(?:\w+\s+)?"
        r"(?:call|time|meeting|follow[\s-]?up|onboarding)\b",
        r"\b(?:what\s+(?:day|time)|when)\s+(?:works|is\s+good|are\s+you\s+free)\b",
        r"\b(?:talk|speak|meet|chat)\s+(?:again\s+)?(?:on|next|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bcalendar\s+invite\b", r"\bsend\s+(?:you\s+)?(?:a|an|the)\s+invite\b"]},
    {"id": "transition", "label": "Transition language", "speaker": "host", "patterns": [r"\bwith\s+that\s+being\s+said\b"]},
    {"id": "validate", "label": "Validated before answering", "speaker": "host", "patterns": [
        r"\babsolutely\b", r"\bthat's\s+(?:totally\s+|completely\s+)?(?:normal|fair)\b", r"\bno\s+issue\b",
        r"\bI\s+(?:totally\s+|completely\s+)?(?:get|hear|understand)\s+(?:that|you|it)\b"]},
    {"id": "price_ask", "label": "They asked about price", "speaker": "guest", "patterns": [
        r"\bwhat\s+(?:are|is)\s+(?:your|the)\s+(?:price|prices|pricing|fee|fees|cost|costs|rate|rates)\b",
        r"\bhow\s+much\s+(?:is|does|do|would|will)\s+(?:it|this|that|you)\b",
        r"\bwhat\s+do(?:es)?\s+(?:it|this|that)\s+cost\b", r"\bwhat\s+do\s+you\s+charge\b", r"\bpricing\b",
        r"\b(?:go\s+over|what\s+about|tell\s+me)\s+(?:the\s+|your\s+)?(?:price|prices|cost|fees?)\b"]},
]

OBJECTIONS = [
    {"id": "money", "label": "Money or budget", "patterns": [
        r"\bafford\b", r"\bbudget\b", r"\bexpensive\b", r"\btoo\s+much\b", r"\bcash\s+flow\b", r"\bthat's\s+a\s+lot\b",
        r"\bcan't\s+(?:pay|spend)\b"]},
    {"id": "partner", "label": "Needs to talk to someone", "patterns": [
        r"\b(?:talk|speak|check|discuss|run\s+(?:it|this)\s+by)\s+(?:\w+\s+){0,2}(?:with\s+)?(?:my|our)\s+(?:wife|husband|partner|partners|"
        r"spouse|team|business\s+partner|brother|sister|son|daughter|accountant|family|mom|dad)\b"]},
    {"id": "think", "label": "Think about it / not now", "patterns": [
        r"\bthink\s+(?:about\s+it|it\s+over)\b", r"\bsleep\s+on\s+it\b", r"\bget\s+back\s+to\s+you\b",
        r"\bnot\s+(?:right\s+)?now\b", r"\bnext\s+(?:year|month|quarter)\b", r"\bafter\s+the\s+holidays\b"]},
    {"id": "send_info", "label": "Send me info (smoke screen)", "patterns": [
        r"\bsend\s+(?:me|it|that|this|over)\s+(?:\w+\s+){0,4}(?:pdf|info|information|details|proposal|something|email|document|deck)\b",
        r"\bin\s+(?:a\s+)?pdf\b", r"\bemail\s+(?:me|it)\b"]},
    {"id": "burned", "label": "Burned by an agency before", "patterns": [
        r"\b(?:tried|used|hired|worked\s+with)\s+(?:an?\s+)?(?:\w+\s+)?(?:agency|agencies|marketing\s+(?:company|guy|firm))\b",
        r"\bburned\b", r"\bscam\w*\b", r"\bripped\s+off\b", r"\bbeen\s+pitched\b"]},
    {"id": "proof", "label": "Wants proof or references", "patterns": [
        r"\bhow\s+do\s+I\s+know\b", r"\bproof\b", r"\breferences?\b", r"\bcase\s+stud\w+\b", r"\btestimonials?\b",
        r"\bhave\s+you\s+(?:ever\s+)?(?:worked|done\s+this)\b", r"\bworked\s+with\s+(?:anyone|someone|a\s+client)\b"]},
    {"id": "staffing", "label": "Staffing", "patterns": [
        r"\bshort[\s-]?staffed\b", r"\bstaff(?:ing)?\s+(?:is|are|shortage|problem|issue)\b",
        r"\bcan't\s+(?:find|keep)\s+(?:staff|caregivers|help)\b"]},
    {"id": "terms", "label": "Payment terms", "patterns": [
        r"\bpay\s+(?:you\s+)?(?:before|prior|upfront|up\s+front|after|when|once)\b", r"\bcontract\b",
        r"\block(?:ed)?\s+in\b", r"\bmove[\s-]?ins?\b[^.?!]{0,30}\bpay\b", r"\bpay\b[^.?!]{0,30}\bmove[\s-]?ins?\b"]},
    {"id": "already_have", "label": "Already has something", "patterns": [
        r"\b(?:we|I)\s+(?:already\s+)?(?:have|use|work\s+with)\s+(?:a\s+|an\s+)?(?:placement|referral|marketing|agency|someone)\b",
        r"\bwe're\s+(?:fine|good|full)\b", r"\bdon't\s+need\b"]},
    {"id": "location", "label": "Location / distance", "patterns": [r"\btoo\s+far\b", r"\blocation\b", r"\brural\b"]},
]

PROMISE = [
    r"\bI(?:'ll|\s+will|'m\s+(?:going\s+to|gonna)|\s+am\s+going\s+to|\s+can|\s+could)\s+(?:\w+\s+){0,2}?"
    r"(?:send|email|text|get|share|forward|follow\s+up|call|put\s+together|make|write|look\s+into|check|find|record|"
    r"shoot|set\s+up|book|draft|build|prepare|pull|grab|loop|copy)\b",
    r"\blet\s+me\s+(?:send|get|check|find|put|look|grab|pull)\b",
    r"\bwe(?:'ll|\s+will)\s+(?:send|get|set\s+up|build|have|follow)\b",
]
# Lines that look like a promise but are just the call moving along.
PROMISE_EXCLUDE = r"\bshare\s+(?:my|the)\s+screen\b|\bask\s+you\b|\brun\s+you\s+through\b|\bget\s+(?:you\s+)?started\b"

MONEY = (r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k\b|thousand\b|million\b)?|\b\d[\d,]*(?:\.\d+)?\s?k\b|"
         r"\b\d[\d,]*(?:\.\d+)?\s+(?:dollars|bucks|grand)\b|"
         r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty)\s+(?:thousand|grand)\b")
PRICE_CONTEXT = (r"\b(?:fee|fees|price|prices|pricing|cost|costs|invest\w*|charge\w*|pay\s+(?:us|me)|per\s+(?:month|day)|"
                 r"a\s+(?:month|day)|deposit|set[\s-]?up|upfront|up\s+front|retainer|total|comes?\s+(?:out\s+)?to|in\s+ads|"
                 r"for\s+the\s+(?:full\s+)?(?:90|ninety)\s+days|program|package)\b|/\s?(?:mo|day)\b")

# Scorecard rows. "auto" rows get a Python verdict with evidence; the model confirms or overrides each one.
RUBRIC_ITEMS = [
    ("Q1", "Was there a huge problem, said out loud?"),
    ("Q2", "Do you know why they don't have it already?"),
    ("Q3", "Did you get a commitment to change?"),
    ("S1", "Open: no good-time ask, 2 to 5 min rapport, frame set"),
    ("S2", "Problem: they described it in detail, you restated it sharper"),
    ("S3", "Timeline: how long has this been an issue"),
    ("S4", "Tried: what have you tried in that time"),
    ("S5", "Cost: what is it costing you"),
    ("S6", "Three layers: want, doing, why it has not changed"),
    ("S7", "Goal: humble goal or actual goal"),
    ("S8", "Capacity screen before any resident promise"),
    ("S9", "Commitment to change before the pitch"),
    ("S10", "Decision maker check before the pitch"),
    ("S11", "Pitch tailored to their words, tie-downs not 'any questions'"),
    ("S12", "Price after commitment, their numbers first, quiet after the price"),
    ("S13", "Objections: validate first, smoke screens, logistical stack to deposit"),
    ("S14", "Offer rules: tier prescribed, guarantee by tier, deadline true"),
    ("S15", "Close or deposit asked, next call booked with a date"),
    ("J1", "Your directives: talk less, no long monologues, stop after the ask"),
]
RESULTS = ("pass", "partial", "miss", "n/a")

REMINDERS = [
    {"id": "W1", "text": "Get the 3: huge problem, why not solved yet, a yes to change.", "signals": ["always"]},
    {"id": "W2", "text": "Ask, then stop. You talk yourself out of the close.", "signals": ["always", "close", "follow_up"]},
    {"id": "W3", "text": "Faster, louder, more tone.", "signals": ["always"]},
    {"id": "W5", "text": "Timelines win the close: how long, what tried, what it costs.", "signals": ["prior_no_timeline", "first_call"]},
    {"id": "W6", "text": "Extend the placement agents, never knock them.", "signals": ["placement_agents"]},
    {"id": "W7", "text": "Ask early: anyone else in this decision? A logistical stack means deposit.", "signals": ["partner"]},
    {"id": "W8", "text": "Capacity screen before any resident promise: could you staff 5 more tours?", "signals": ["many_empty", "staffing"]},
    {"id": "W9", "text": "Find why they never bought before. Spend it at the close.", "signals": ["burned"]},
    {"id": "W10", "text": "Downsell by asking: is that ad budget something you can do?", "signals": ["low_budget", "small_home"]},
    {"id": "W11", "text": "Build the problem before the doc opens. No pitch before a yes to change.", "signals": ["prior_price_early", "send_info_asker"]},
    {"id": "W12", "text": "Validate every objection first, then answer, then ask again.", "signals": ["follow_up", "objections_open"]},
    {"id": "W13", "text": "Numbers, flat tone, no hype.", "signals": ["skeptic"]},
    {"id": "W14", "text": "Not senior living? Route out fast. Do not rebuild them.", "signals": ["scope_risk"]},
    {"id": "W15", "text": "Book the next call before you hang up.", "signals": ["prior_no_next_step", "follow_up"]},
]

EXPECT = [
    {"id": "O1", "says": "I already use placement agents.", "move": "Extend, don't knock. Their numbers: fee times residents vs ad spend.",
     "signals": ["placement_agents"]},
    {"id": "O2", "says": "I need to talk to my partner.", "move": "Ask early what kind of partner and how involved. Logistical: deposit.",
     "signals": ["partner"]},
    {"id": "O3", "says": "Let me think about it.", "move": "Validate. What part, exactly? 1 to 10 check.", "signals": ["always"]},
    {"id": "O4", "says": "I can't afford ads right now.", "move": "Break-even screen first. Downsell by asking. No financing below break-even.",
     "signals": ["low_budget", "small_home"]},
    {"id": "O5", "says": "I tried an agency and it didn't work.", "move": "What happened, exactly? That reason is your close.",
     "signals": ["burned"]},
    {"id": "O6", "says": "Who else have you done this for?", "move": "Let the guarantee carry the risk.",
     "signals": ["trust_asker", "skeptic"]},
    {"id": "O7", "says": "Send me a PDF.", "move": "Smoke screen. What would you look for in it? Book the next call first.",
     "signals": ["send_info_asker"]},
    {"id": "O8", "says": "I'm short staffed.", "move": "Capacity screen. Tours guarantee only.", "signals": ["staffing"]},
    {"id": "O9", "says": "Do I pay before anyone moves in?", "move": "One setup fee vs a placement fee per move-in. Use their numbers.",
     "signals": ["terms_asker", "placement_agents"]},
    {"id": "O10", "says": "Families say we're too far.", "move": "The qualifying questions screen distance before they call.",
     "signals": ["rural"]},
]

# Simple keyword signals the prep step can read off text it already has (their reply, notes, a prior summary).
SIGNAL_WORDS = {
    "placement_agents": r"\bplacement\b|\breferral\s+agen\w+\b|\ba\s+place\s+for\s+mom\b",
    "partner": r"\b(?:wife|husband|spouse|business\s+partner|my\s+partner|co-?owner)\b",
    "low_budget": r"\bafford\b|\bbudget\b|\btight\b|\bcan't\s+spend\b",
    "burned": r"\b(?:tried|hired|used)\s+(?:an?\s+)?(?:\w+\s+)?agenc\w+\b|\bburned\b|\bscam\w*\b|\bdidn't\s+work\b",
    "staffing": r"\bshort[\s-]?staffed\b|\bstaff(?:ing)?\b|\bcaregivers?\b",
    "send_info_asker": r"\bsend\s+(?:me\s+)?(?:\w+\s+){0,3}(?:pdf|info|information|details|proposal)\b",
    "rural": r"\brural\b|\btoo\s+far\b|\bcountry\b",
    "trust_asker": r"\bproof\b|\breferences?\b|\bresults\b|\btestimonials?\b|\bcase\s+stud\w+\b|\bworked\s+with\b",
    "skeptic": r"\bskeptic\w*\b|\bshow\s+me\b|\bon\s+paper\b|\bguarantee\b",
    "terms_asker": r"\bpay\s+(?:you\s+)?(?:before|after|upfront|up\s+front)\b|\bper\s+move[\s-]?in\b",
    "scope_risk": r"\brecovery\b|\bsober\b|\bre-?entry\b|\bskilled\s+nursing\b|\bnursing\s+home\b|\bSNF\b",
}


def compile_all(patterns):
    return [re.compile(p, re.I) for p in patterns]
