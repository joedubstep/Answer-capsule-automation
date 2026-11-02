"""Shared test corpus for the Copy Checker (synthetic text only, no real people or homes).

Each case: id, context, text, opts (require_link / require_optout / template), and what must be true:
  expect  rule ids that must fire (a rule listed twice must fire at least twice)
  absent  rule ids that must NOT fire (false-positive guards)
  ok      expected pass/fail, when it matters
  clean   True when the text must produce no issues at all
test_corpus.py checks these in Python; test_parity.py runs every case through the page's JavaScript
and demands the same answer. Special characters are built with chr() so this file stays plain ASCII.
"""
EM, EN = chr(0x2014), chr(0x2013)
LSQ, RSQ, LDQ, RDQ, ELL = chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D), chr(0x2026)
NBSP = chr(0xA0)
PRAY, THUMB, SKIN, SMILE = chr(0x1F64F), chr(0x1F44D), chr(0x1F3FD), chr(0x1F600)
ZWJ, MAN, WOMAN, GIRL = chr(0x200D), chr(0x1F468), chr(0x1F469), chr(0x1F467)
CHECK, STAR = chr(0x2705), chr(0x2B50)

PE, PS, CL, IN = "prospect_email", "prospect_sms", "client", "internal"

LONG_HARD = ("Our comprehensive organizational methodology systematically evaluates operational inefficiencies "
             "across residential communities, identifying opportunities for considerable improvement. "
             "Administrators consistently appreciate the transparency and accountability this methodology "
             "provides throughout implementation.")

def odd_inputs(n=20000):
    """Big, strange pastes that once made a regex backtrack for minutes. Each must check in well under a second."""
    raw = {
        "brackets": "[name x ", "brackets2": "[a b ", "dotted": "a.", "digits": "1.", "dotword": "word.",
        "angle": "< name ", "angle_caps": "<NAME ", "braces": "{a ", "under": "a_", "at": "a@b.", "dollar": "$1,",
        "excl": "a! ", "hyph": "a - ", "spaces": "a ", "caps": "Oak ", "lead": "lead ", "q": "Open? ",
        "pct": "5 % ", "quote_dot": ".\"", "emoji": "ok " + chr(0x1F600) + " ", "leverage": "We Leverage ",
    }
    return {k: (v * (n // len(v) + 1))[:n] for k, v in raw.items()}


CASES = [
    # ---------------------------------------------------------------- clean copy (no issues at all)
    dict(id="good_sms", context=PS, text="Hi Pat, it's Joey at Surven. Did I miss you the first time?", clean=True),
    dict(id="good_email", context=PE, clean=True, text=(
        "Hi Pat,\n\nI saw Oak Hill has two rooms listed on your website.\n\n"
        "The mornings the phone rings and nobody can get to it are the ones I work on.\n\n"
        "Worth a call?\n\nJoey\nSurven")),
    dict(id="good_client", context=CL, clean=True,
         text="Hi Pat, three families asked about a room this week. Two toured. One moved in on Friday."),
    dict(id="good_internal", context=IN, clean=True, text="Call Pat at Oak Hill today. Ask about the open room. Log it after."),
    dict(id="good_roi", context=PE, clean=True, text="The ROI is clear. Want to see it?"),
    dict(id="good_result_phrase", context=PE, clean=True,
         text="That is the part I work on: filling your empty beds."),
    dict(id="good_bullets", context=CL, clean=True,
         text="This week:\n- Two tours booked\n- One move-in\n* Calls answered fast\n1. Next: the open house"),
    dict(id="empty", context=PS, text="", clean=True, ok=True),
    dict(id="whitespace_only", context=PE, text="  \n\n\t ", clean=True, ok=True),

    # ---------------------------------------------------------------- false-positive guards
    dict(id="fp_scoreboard_gradual", context=PE, absent=["cold_outreach_words"],
         text="The scoreboard was gradual to update. We upgraded the gradebook and the scorecard."),
    dict(id="fp_realistic_organism", context=IN, absent=["british_spelling", "british_ise"],
         text="That is a realistic plan. Every organism needs care. The cancellation is done. A specialist came."),
    dict(id="fp_patient_adjective", context=CL, absent=["patients"],
         text="Thanks for being patient with us. Please be patient a little longer."),
    dict(id="fp_leads_to", context=CL, absent=["leads_for_families"],
         text="A fast reply leads to a tour. Good service leads into referrals. The lead time is short."),
    dict(id="fp_dial_in_number", context=CL, absent=["buzzword"], text="Here is the dial-in number for the call."),
    dict(id="fp_meta_engine", context=CL, absent=["meta_only_ads"], text="Your Meta Ads Engine is live today."),
    dict(id="fp_memory_care_homes", context=PE, absent=["care_home", "care_home_name"],
         text="We work with memory care homes, personal care homes and board and care homes."),
    dict(id="fp_names_mid_sentence", context=PE, absent=["buzzword", "british_spelling", "british_ise"],
         text="Hi Pat, I saw Empower Pines Living and Maple Centre Commons on the state list."),
    dict(id="fp_template_merge", context=CL, opts={"template": True}, absent=["merge_field"],
         text="Hi {{contact.first_name}}, your tour at {{ location.name }} is set."),
    dict(id="fp_abbreviations", context=CL, absent=["lowercase_start"],
         text="Dr. Example will join at 3 p.m. on the tour, e.g. the second one. It went well."),
    dict(id="fp_domain_start", context=CL, absent=["lowercase_start"], text="Book here. surven.ai/book is the page."),
    dict(id="fp_iphone_start", context=CL, absent=["lowercase_start"], text="Thanks. iPhone photos are fine."),
    dict(id="fp_ranges", context=CL, absent=["spaced_hyphen", "dash"], text="Tours run 9 to 5, Monday to Friday."),
    dict(id="fp_soft_wrap", context=PE, absent=["lowercase_start"],
         text="Hi Pat,\n\nWe help homes like yours answer\nthe phone when nobody can.\n\nJoey"),
    dict(id="fp_ellipsis", context=CL, absent=["lowercase_start"], text="Well... we can talk Monday."),
    dict(id="fp_colon_letters", context=CL, absent=["emoticon"], text="Note:Do this today (ok:)"),
    dict(id="fp_client_numbers", context=CL, absent=["statistics", "price_before_call"],
         text="You had 12 calls and 3 tours. That is 25% more than last week. The invoice is $500."),
    dict(id="fp_markdown_link", context=CL, absent=["merge_field"],
         text="See [the page](https://example.com/page) and [Home](https://example.com)."),
    dict(id="fp_times", context=PS, absent=["statistics"], text="I can call at 2 in the afternoon."),
    dict(id="fp_never_have_to", context=PE, absent=["blame_person"], text="You never have to answer the phone again."),
    dict(id="fp_homes_fill_rooms", context=PE, absent=["result_phrase"],
         text="Most homes fill rooms through word of mouth."),
    dict(id="fp_internal_care_home", context=IN, absent=["care_home"], text="Pat runs a care home in Ohio."),
    dict(id="fp_ascii_hyphen_words", context=PE, absent=["dash", "spaced_hyphen"],
         text="It is a well-known, five-minute fix."),
    dict(id="fp_upgrade", context=PS, absent=["cold_outreach_words"], text="Want the upgrade?"),
    dict(id="fp_question_comma", context=PS, absent=["long_ask"],
         text="Hi Pat, it's Joey at Surven, do you have any open rooms at Oak Hill Senior Living Center right now?"),
    dict(id="fp_leads_verb", context=PE, absent=["leads_for_families"],
         text="Pat leads the front desk. Who leads admissions there? She leads tours on Fridays."),
    dict(id="fp_lead_job_titles", context=CL, absent=["leads_for_families"],
         text="Your lead caregiver called back. The lead nurse and the new lead med tech helped. Pat took the lead."),
    dict(id="fp_stat_time_units", context=PS, absent=["statistics"],
         text="I can call at 9 in two weeks. I called three times the first week. Back at 1 in 10 minutes."),
    dict(id="fp_pm_then_new_sentence", context=CL, absent=["long_sentence"],
         text=("We can meet at 3 p.m. The tour team will walk you through every room and the dining hall and "
               "the garden out back.")),
    dict(id="fp_question_mark_in_link", context=PS, absent=["multi_question"],
         text="Did I miss you? Pick a time: https://example.com/book?ref=sms"),
    dict(id="fp_bare_domain_link", context=PS, absent=["multi_question", "lowercase_start"],
         text="Did I miss you? Times are at start.example.com/booking-page?src=text"),
    dict(id="fp_quoted_name", context=PE, absent=["buzzword"], text="I saw \"Empower Pines\" on the state list."),

    # ---------------------------------------------------------------- each rule fires
    dict(id="dash_variants", context=PE, ok=False, expect=["dash", "dash", "dash", "dash", "dash"],
         text="One " + EM + " two " + EN + " three &mdash; four &#8212; five &ndash; six."),
    dict(id="spaced_hyphen", context=PE, expect=["spaced_hyphen"], text="We help - fast."),
    dict(id="buzzwords", context=PE, ok=False, expect=["buzzword"] * 6,
         text="This is a game changer. A load-bearing deep-dive. We got dialed in and seamless. Holistic too."),
    dict(id="buzzword_internal_warn", context=IN, ok=True, expect=["buzzword"], text="We should leverage the list."),
    dict(id="british", context=PE, ok=False,
         expect=["british_spelling"] * 9 + ["british_ise"] * 2,
         text=("Thanks for the enquiry. The colour is grey. I realise it. Our organisation can help whilst you wait. "
               "I will ring you straight away. It was cancelled. Her speciality is memory care. "
               "Your mum is in hospital.")),
    dict(id="care_home_block", context=CL, ok=False, expect=["care_home"], text="Your care home is full."),
    dict(id="care_home_name_warn", context=PE, expect=["care_home_name"], absent=["care_home"],
         text="Hi Pat, is Oak Hill Care Home still open?"),
    dict(id="patients", context=CL, ok=False, expect=["patients", "patients"],
         text="The patients love it. Each new patient gets a tour."),
    dict(id="leads", context=PE, ok=False, expect=["leads_for_families", "leads_for_families"],
         text="We send you more leads. Every new lead gets a call."),
    dict(id="cold_words", context=PE, ok=False, expect=["cold_outreach_words"] * 3,
         text="I ran an audit and a quick assessment. Your grade is low."),
    dict(id="cold_words_client_ok", context=CL, absent=["cold_outreach_words"], text="I ran an audit of the calls."),
    dict(id="bad_time_ask", context=PS, ok=False, expect=["bad_time_ask"], text="Is now a bad time?"),
    dict(id="good_time_to_talk", context=PE, ok=False, expect=["bad_time_ask"], text="When is a good time to talk?"),
    dict(id="bad_time_client_warn", context=CL, ok=True, expect=["bad_time_ask"], text="Is now a good time to talk?"),
    dict(id="price", context=PE, ok=False, expect=["price_before_call"] * 5,
         text="It is $500. Or $1,500/mo. That is 500 dollars per month. The monthly fee is low."),
    dict(id="stats", context=PS, ok=False, expect=["statistics"] * 5,
         text="40% more tours. 3x the calls. Three times more families. 8 out of 10 pick fast. 2 in 5 wait."),
    dict(id="research_claim", context=PE, expect=["research_claim"], text="Studies show families pick fast homes."),
    dict(id="banned_stat_client", context=CL, ok=False, expect=["banned_stat"], absent=["statistics"],
         text="75% of families choose the first community to respond."),
    dict(id="invented_results", context=PE, ok=False, expect=["invented_results"] * 3,
         text="Our clients see more tours. We helped twelve homes. The homes we work with get calls."),
    dict(id="emoji", context=PS, ok=False, expect=["emoji", "emoji", "sms_unicode"],
         text="Thanks " + PRAY + " talk soon " + THUMB + SKIN),
    dict(id="emoji_zwj_family", context=PE, ok=False, expect=["emoji"],
         text="For the whole family " + MAN + ZWJ + WOMAN + ZWJ + GIRL + " today."),
    dict(id="emoji_symbols", context=PE, ok=False, expect=["emoji", "emoji"], text="Done " + CHECK + " and " + STAR),
    dict(id="emoji_client_warn", context=CL, ok=True, expect=["emoji"], text="Great tour today " + SMILE),
    dict(id="emoticon", context=PS, expect=["emoticon"], text="Thanks :) see you."),
    dict(id="tldr", context=IN, ok=False, expect=["tldr"], text="TL;DR: call Pat today."),
    dict(id="idioms", context=PE, expect=["idiom", "idiom"],
         text="No family should fall through the cracks. That is low-hanging fruit."),
    dict(id="needy", context=PE, expect=["needy_hedge"] * 3,
         text="Just checking in. Sorry to bother you. Even one name helps."),
    dict(id="curly_needy", context=PE, expect=["needy_hedge"], text="Hope you" + RSQ + "re well."),
    dict(id="justify", context=PE, expect=["justify_clause", "justify_clause"],
         text="Reply here and I'll work around you. I'll stop here so I'm not another vendor in your inbox."),
    dict(id="filler", context=PE, expect=["filler", "filler"],
         text="Quick question for you. I wanted to reach out about Oak Hill."),
    dict(id="hype", context=PE, expect=["hype"], text="This is amazing news for Oak Hill."),
    dict(id="merge_fields", context=PE, ok=False, expect=["merge_field"] * 8,
         text=("Hi {first}, {{contact.first_name}} and [Name] and <NAME> at [HOME NAME]. We have XX rooms. "
               "Date TBD. Sign here ___.")),
    dict(id="merge_internal_warn", context=IN, ok=True, expect=["merge_field"], text="Ask {first} about it."),
    dict(id="lowercase", context=CL, expect=["lowercase_start", "lowercase_start"],
         text="thanks for the call. we can start Monday."),
    dict(id="lowercase_after_greeting_line", context=PS, expect=["lowercase_start"],
         text="Hi Pat,\nit's Joey at Surven."),
    dict(id="long_sentence", context=CL, expect=["long_sentence"],
         text=("We called every family back the same day and booked two tours and one of them came in with "
               "their daughter and stayed for lunch.")),
    dict(id="grade_block_prospect", context=PE, ok=False, expect=["reading_grade_too_high"],
         absent=["reading_grade_high"], text=LONG_HARD),
    dict(id="grade_warn_internal", context=IN, expect=["reading_grade_high"], absent=["reading_grade_too_high"],
         text=LONG_HARD),
    dict(id="multi_question", context=PS, expect=["multi_question"], text="Open rooms? Want help?"),
    dict(id="multi_question_email_ok", context=PE, absent=["multi_question"], text="Open rooms? Want help?"),
    dict(id="long_ask", context=PE, expect=["long_ask"],
         text="Would you be open to a short call next week to talk about how your front desk handles the calls?"),
    dict(id="exclamation", context=PE, expect=["exclamation", "exclamation"], text="Great to meet you! Talk soon!!"),
    dict(id="url_shortener", context=PS, ok=False, expect=["url_shortener"], text="See bit.ly/abc123 for the page."),
    dict(id="chargeback", context=IN, ok=False, expect=["chargeback"], text="File the charge-back today."),
    dict(id="death_spiral", context=CL, ok=False, expect=["death_spiral"], text="Empty rooms start a death spiral."),
    dict(id="vfd_client", context=CL, ok=False, expect=["virtual_front_desk"], text="Your Virtual Front Desk is live."),
    dict(id="vfd_internal", context=IN, ok=True, expect=["virtual_front_desk"], text="Rename the virtual front desk."),
    dict(id="byaf", context=PE, expect=["byaf"], text="But you are free to say no."),
    dict(id="meta_only", context=CL, expect=["meta_only_ads"], text="Your Facebook ads are live."),
    dict(id="deposit", context=CL, expect=["trial_deposit"], text="We got your deposit."),
    dict(id="blame", context=PE, expect=["blame_person", "blame_person"],
         text="You missed my call. You didn't reply."),
    dict(id="outcome", context=PE, expect=["outcome_claim", "result_phrase"], text="We will fill your rooms."),
    dict(id="result_phrase_variant", context=CL, expect=["result_phrase"], text="This is about filling your open beds."),
    dict(id="sms_unicode", context=PS, expect=["sms_unicode"],
         text="It" + RSQ + "s Joey. " + LDQ + "Hi" + RDQ + ELL),
    dict(id="sms_length", context=PS, expect=["sms_length"], text=("Short line here. " * 25).strip()),
    dict(id="missing_link", context=PE, ok=False, opts={"require_link": True}, expect=["missing_link"],
         text="Want to talk?"),
    dict(id="has_link", context=PE, opts={"require_link": True}, absent=["missing_link"],
         text="Pick a time: https://example.com/book/surven"),
    dict(id="has_surven_link", context=PS, opts={"require_link": True}, absent=["missing_link"],
         text="Pick a time here: surven.ai/booking-page"),
    dict(id="missing_optout", context=PS, ok=False, opts={"require_optout": True}, expect=["missing_optout"],
         text="Hi Pat, it's Joey at Surven."),
    dict(id="has_optout", context=PS, opts={"require_optout": True}, absent=["missing_optout"],
         text="Hi Pat, it's Joey at Surven. Reply STOP to opt out."),
    dict(id="flags_off_no_check", context=PS, absent=["missing_link", "missing_optout"], text="Hi Pat."),

    # ---------------------------------------------------------------- holes found in review
    dict(id="dash_rare_forms", context=CL, ok=False, expect=["dash"] * 3,
         text="One &mdash two &#8211 three " + chr(0x2E3A) + " four."),
    dict(id="leads_still_caught", context=PE, ok=False, expect=["leads_for_families"] * 2,
         text="We send more leads the same day. Who gets the lead first?"),
    dict(id="bullet_buzzword", context=CL, ok=False, expect=["buzzword"] * 3,
         text="This week:\n- Streamlined the intake\n2. Leverage the list\n\"Seamless\" is the word."),
    dict(id="bad_time_variants", context=PE, ok=False, expect=["bad_time_ask"] * 2,
         text="Would now be a good time? Is this an okay time?"),
    dict(id="invented_variants", context=PE, ok=False, expect=["invented_results"] * 3,
         text="Clients typically see more tours. A client in Ohio got ten tours. It is a home we work with."),
    dict(id="british_isational", context=PE, ok=False, expect=["british_ise"] * 2,
         text="Our organisational chart is short. The realisation came late."),
    dict(id="british_more", context=CL, ok=False, expect=["british_spelling"] * 3,
         text="It is a single storey home with a cosy room by the harbour."),
    dict(id="needy_hope_youre", context=PE, expect=["needy_hedge"], text="Hope you're having a good week."),
    dict(id="price_a_month", context=PE, ok=False, expect=["price_before_call"] * 2,
         text="It is 500 a month. Or five hundred a month."),
    dict(id="merge_name_tokens", context=PE, ok=False, expect=["merge_field"] * 2,
         text="Hi FIRST_NAME, this is about first_name."),
    dict(id="fp_pm_lowercase_no_split", context=CL, absent=["lowercase_start"],
         text="Call me at 3 p.m. then we talk. Thanks etc. we can start."),

    # ---------------------------------------------------------------- text handling
    dict(id="crlf_nbsp", context=CL, expect=["lowercase_start"], text="Hi Pat,\r\nwe can" + NBSP + "talk."),
    dict(id="markdown_bold", context=CL, absent=["long_sentence"],
         text=("**Inside every tool.** Every draft goes through the same rules before it lands. "
               "That is _the point._ Then `check.py` runs. Done.")),
    dict(id="links_not_graded", context=PE, absent=["reading_grade_high", "reading_grade_too_high"],
         text=("Hi Pat, here is the page. Pick a time that works at https://example.com/booking/organization-"
               "consultation-appointment-calendar or write to scheduling.coordinator@example.com today. Thanks.")),
    dict(id="line_numbers", context=CL, expect=["care_home"], text="Hi Pat,\n\nThanks.\nYour care home is full."),
    dict(id="mixed_everything", context=PS, ok=False,
         expect=["dash", "buzzword", "emoji", "price_before_call", "care_home", "invented_results", "lowercase_start"],
         text=("hi Pat " + EM + " leverage our clients" + RSQ + " results " + SMILE + " at your care home for $300.\n"
               "is now ok?")),
]
