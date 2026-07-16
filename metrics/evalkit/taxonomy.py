"""Canonical taxonomies: flow stages, anomalies, check names, error buckets.

Detector regexes were mined from the two agents' transcript corpora and
validated against all 472 transcripts. Per-format detectors map onto ONE
canonical stage/anomaly vocabulary so every report shows the same rows.

Generated from workflow analysis; edit deliberately and bump metrics
SCHEMA_VERSION if canonical definitions change.
"""

import re

# ---- per-format raw stage detectors (source keys) ----
STAGE_RX = {
  'alpha': {
    'bot_greeting': '(?im)^\\*\\*🤖 BOT\\*\\* \\[greeting\\]:\\s*Hi there! I will be your virtual assistant today',
    'language_options_offered': '(?im)^\\*\\*🤖 BOT\\*\\* \\[greeting\\]:\\s*§W§OPTIONS§\\s*English\\s*•\\s*Français',
    'ai_privacy_disclosure': '(?i)§W§BANNER§[^\\n]*automated chatbot which uses AI[^\\n]*Privacy Notice',
    'customer_disruption_intent': '(?im)^\\*\\*🧑 CUSTOMER\\*\\*(?: \\[[^\\]]*\\])?:\\s[^\\n]*flight[^\\n]*(?:delay|cancel|disrupt)[^\\n]*(?:compensation|eligib|claim)',
    'language_confirmed': "(?i)I(?:'|’)ll (?:be assisting|assist) you in (?:English|French)",
    'regulation_reference': '(?i)Air Passenger Protection Regulations|\\bAPPR\\b|E[CU] ?261|UK ?261',
    'compensation_tiers_quoted': '(?is)(?:\\$\\s?400|CAD\\s?400|400\\s?CAD).{0,400}?(?:\\$\\s?700|CAD\\s?700|700\\s?CAD).{0,400}?(?:\\$\\s?1,?000|CAD\\s?1,?000|1,?000\\s?CAD)',
    'compensation_amount_quoted_provisional': '(?i)(?:you (?:would|may) be eligible for|you may be entitled to)\\s*\\*{0,2}\\$\\s?(?:400|700|1,?000)\\s*(?:CAD)?\\*{0,2}\\s*(?:in\\s+)?compensation|the compensation amount is\\s*\\*{0,2}\\$?\\s?(?:400|700|1,?000)\\s*(?:CAD)?',
    'claim_start_offer': '(?i)Would you like me to (?:help you )?(?:start|get started with|file)[^\\n?]{0,80}claim[^\\n?]{0,40}\\?',
    'customer_accepts_claim_start': '(?im)^\\*\\*🧑 CUSTOMER\\*\\*(?: \\[[^\\]]*\\])?:\\s[^\\n]*(?:start|file|proceed with|submit)[^\\n]{0,40}\\bclaim\\b',
    'bot_claim_intent_ack': "(?i)\\*\\*🤖 BOT\\*\\*[^\\n]*(?:(?:help you|assist you with|get(?:ting)? (?:that |you )?started|Let(?:'|’)s get started|I(?:'|’)ll (?:help|get started)|I can help)[^\\n]{0,80}?(?:compensation claim|claim for|delay claim|claim now|claim\\b))",
    'automated_decision_disclosure': '(?i)§W§BANNER§[^\\n]*assessment and decision regarding your request will be made through an automated decision-making process',
    'claim_requirements_listed': "(?i)To file your claim, you(?:'|’)ll need your booking reference",
    'identity_request': "(?is)(?:To get started|I(?:'|’)ll need a few details|need to find your booking).{0,400}?booking reference",
    'identity_provided': '(?m)^\\*\\*🧑 CUSTOMER\\*\\*(?: \\[[^\\]]*\\])?:\\s[^\\n]*(?:(?i:booking(?: reference)?|reference|PNR)\\b[^\\n]{0,30}?\\b[A-Z]{6}\\b|\\b[A-Z]{6}\\b[^\\n]{0,30}$)',
    'booking_lookup_ack': '(?i)\\*\\*🤖 BOT\\*\\*[^\\n]*Let me (?:look up|pull up|verify|find) your booking|Let me (?:look|pull) up your booking',
    'otp_channel_selection': '(?is)verify your identity by sending a verification code.{0,200}?§W§INFO§SINGLE_SELECT',
    'otp_channel_chosen': '(?im)^\\*\\*🧑 CUSTOMER\\*\\* \\[widget:SINGLE_SELECT->[^\\]]*\\]:\\s*(?:Email|SMS|Text|Phone)',
    'otp_sent': '(?i)sending a (?:6-digit )?verification code to your email|verification code has been sent to your email|sent a 6-digit verification code to your email',
    'otp_entered': '(?im)^\\*\\*🧑 CUSTOMER\\*\\* \\[mailinator-otp\\]:\\s*\\d{6}\\b',
    'otp_verified': '(?i)Your code has been verified successfully',
    'contact_email_confirmation': '(?i)confirm the email address[^\\n]*(?:claim|further information)|Would you like to use (?:the email address on file: )?\\S*•+\\S*@',
    'country_of_residence_request': '(?i)(?:share|provide)[^\\n]{0,40}country of residence',
    'additional_info_and_receipts': '(?i)share any additional relevant information to help me process your claim|§W§INFO§[^\\n]*receipt[^\\n]*(?:10MB|file size)',
    'manual_contact_info_collection': '(?is)(?:provide|share|collect)[^§]{0,120}?(?:your )?email address(?: and | ?\\n- Your |[^§]{0,20}?)(?:your )?phone number',
    'payment_method_collection': '(?i)preferred method of payment|bank account details|transit number|institution number|where would you like the funds deposited|Interac e-?transfer',
    'claim_submitted': '(?i)Your claim has been submitted!',
    'case_reference_issued': '\\*\\*Reference Number\\*\\*\\s*:?\\s*`?CCD-\\d{7}-[A-Z0-9]{6}\\b',
    'outcome_escalated_manual_review': '(?i)submit(?:ting)?\\s+your (?:claim|case)[^\\n]{0,60}\\bmanual review|send your claim to manual review|manual[- ]review case|claim is now being processed through manual review',
    'outcome_eligible_final': '(?i)(?:good news|congratulations)[^\\n]{0,100}?\\byou (?:are|have been) eligible|your claim has been approved|you (?:are|have been) (?:deemed |confirmed )?eligible for (?:a )?(?:compensation|payment) of',
    'outcome_not_eligible_final': '(?i)(?:unfortunately|we regret to inform)[^\\n]{0,150}not eligible|your claim (?:has been|was|is) (?:denied|rejected|declined)',
    'id_verification_notice': '(?i)§W§BANNER§[^\\n]*ID verification process will be required if you are deemed eligible',
    'wrapup_anything_else': "(?i)\\banything else I can help you with\\b|You(?:'|’)re (?:very )?welcome[^\\n]{0,120}(?:Thank you for choosing Air Canada|Have a great day)",
    'survey_prompt': '(?i)Was this virtual assistant easy to use today\\?',
  },
  'bravo': {
    'greeting': '^🤖 \\*\\*Assistant\\*\\* _\\(greeting\\)_:\\n> How can I help you today\\?',
    'customer_intent': '(?im)^🧑 \\*\\*Customer\\*\\*:\\n> .*\\b(?:claim|compensation|owed|delayed)\\b',
    'passenger_or_behalf_question': 'are you the passenger who experienced the disruption',
    'claim_flow_entry': 'help you create a claim for your disrupted flight',
    'automated_decision_banner': '§W§BANNER§Please note that the assessment and decision regarding your request will be made through an automated decision-making process',
    'consent_to_start': "^> Yes, let'?s go$",
    'full_name_collection': 'full name exactly as it appears on your ticket',
    'booking_reference_collection': '\\*\\*booking reference(?: number| \\(PNR\\))?\\*\\*',
    'identity_confirmation_summary': '(?is)(?:just )?to confirm\\b.{0,200}?booking reference',
    'otp_channel_selection': 'sending a one-time verification code',
    'otp_code_sent': "I've sent a verification code",
    'otp_code_entry': '^> \\d{6}$',
    'identity_verified': '§W§BANNER§Your identity has been verified\\.',
    'booking_retrieved_trip_confirmation': "(?s)Can you confirm that this is the trip you'?re claiming for\\?.{0,120}?§W§FLIGHT§",
    'disruption_assessment': "I've (?:checked your flight details|reviewed (?:the details of your flight|your flight details))",
    'eligibility_eligible': 'entitled to receive a \\*\\*[\\d,]+\\.\\d{2} [A-Z]{3}\\*\\* compensation',
    'eligibility_not_eligible': 'not eligible for compensation',
    'eligibility_no_determination': "can'?t review this case automatically",
    'adverse_decision_extra': "(?i)falls? outside the time limit for submitting|(?:was |delay was )?determined to be outside[^\\n]{0,40}control|was operated by [^\\n]{0,40}(?:reach out to|contact)[^\\n]{0,40}directly",
    'claim_submitted_confirmation': '(?i)(?:has been|been) submitted for agent review|claim (?:has been|was) (?:successfully )?submitted',
    'deposit_country_selection': 'In which country will your reimbursement be deposited\\?',
    'compensation_amount_quoted': 'entitled to receive a \\*\\*[\\d,]+\\.\\d{2} [A-Z]{3}\\*\\* compensation',
    'payment_method_disclosure': 'payment will be made through \\*\\*(?:Interac e-transfer|electronic bank transfer)\\*\\*',
    'payment_email_confirmation': 'only one email address can be used for this compensation',
    'payment_identity_verification': 'verify\\.aircanada\\.com/idv',
    'claim_review_summary': 'Please review your compensation details',
    'claim_submission_consent': 'Would you like me to submit your claim\\?',
    'case_reference_issued': '(?:\\*\\*Case reference:\\*\\*|Your reference is \\*\\*)\\s*CCD-\\d{7}-[A-Z0-9]{6}',
    'wrap_up': 'Is there anything else I can help you with',
    'survey_feedback': '§W§INFO§FEEDBACK',
    'session_end': '^> End chat$',
  },
}

# designed position of each source stage within its own bot's flow
STAGE_POS = {
  'alpha': {
    "bot_greeting": 1,
    "language_options_offered": 2,
    "ai_privacy_disclosure": 3,
    "customer_disruption_intent": 4,
    "language_confirmed": 5,
    "regulation_reference": 6,
    "compensation_tiers_quoted": 7,
    "compensation_amount_quoted_provisional": 7.5,
    "claim_start_offer": 8,
    "customer_accepts_claim_start": 9,
    "bot_claim_intent_ack": 10,
    "automated_decision_disclosure": 11,
    "claim_requirements_listed": 12,
    "identity_request": 13,
    "identity_provided": 14,
    "booking_lookup_ack": 15,
    "otp_channel_selection": 16,
    "otp_channel_chosen": 17,
    "otp_sent": 18,
    "otp_entered": 19,
    "otp_verified": 20,
    "contact_email_confirmation": 21,
    "country_of_residence_request": 22,
    "additional_info_and_receipts": 23,
    "manual_contact_info_collection": 23.5,
    "payment_method_collection": 24,
    "claim_submitted": 25,
    "case_reference_issued": 26,
    "outcome_escalated_manual_review": 27,
    "outcome_eligible_final": 27,
    "outcome_not_eligible_final": 27,
    "id_verification_notice": 28,
    "wrapup_anything_else": 29,
    "survey_prompt": 30
},
  'bravo': {
    "greeting": 1,
    "customer_intent": 2,
    "passenger_or_behalf_question": 3,
    "claim_flow_entry": 4,
    "automated_decision_banner": 5,
    "consent_to_start": 6,
    "full_name_collection": 7,
    "booking_reference_collection": 8,
    "identity_confirmation_summary": 9,
    "otp_channel_selection": 10,
    "otp_code_sent": 11,
    "otp_code_entry": 12,
    "identity_verified": 13,
    "booking_retrieved_trip_confirmation": 14,
    "disruption_assessment": 15,
    "eligibility_eligible": 16,
    "eligibility_not_eligible": 16,
    "eligibility_no_determination": 18,
    "deposit_country_selection": 17,
    "compensation_amount_quoted": 19,
    "payment_method_disclosure": 20,
    "payment_email_confirmation": 21,
    "payment_identity_verification": 22,
    "claim_review_summary": 23,
    "claim_submission_consent": 24,
    "case_reference_issued": 25,
    "wrap_up": 26,
    "survey_feedback": 27,
    "session_end": 28,
    "adverse_decision_extra": 16,
    "claim_submitted_confirmation": 24
},
}

ANOMALY_RX = {
  'alpha': {
    'first_query_dropped_language_reset': "(?ims)^\\*\\*🧑 CUSTOMER\\*\\* \\[widget:QUICK_REPLIES->[^\\]]*\\]:[^\\n]+\\n+\\*\\*🤖 BOT\\*\\*:\\s*Great! I(?:'|’)ll (?:be assisting|assist) you in",
    'customer_forced_to_repeat': "(?i)\\*\\*🧑 CUSTOMER\\*\\* \\[[^\\]]*(?:re-?stat|re-?send|re-?provid|repeat|didn(?:'|’)?t catch|seems? to have reset|not processed my first)[^\\]]*\\]",
    'otp_timeout_nag': "(?im)^\\*\\*🤖 BOT\\*\\* \\[otp-prompt\\]:\\s*§W§BANNER§[^\\n]*(?:still there|been quiet|haven(?:'|’)t heard back)",
    'otp_fetch_failure': '(?i)No Mailinator OTP matching',
    'booking_lookup_failure': "(?i)(?:wasn(?:'|’)t|not) able to (?:identify|find)[^\\n]{0,40}booking",
    'booking_lookup_loop': "(?is)(?:wasn(?:'|’)t|not) able to (?:identify|find)[^\\n]{0,40}booking.*?(?:wasn(?:'|’)t|not) able to (?:identify|find)[^\\n]{0,40}booking",
    'escalation_to_human': '(?i)connect(?:ed)?(?: you)? with someone who can|speak with a human agent|speak with an agent|manual[- ]review case|help you file your claim manually|help manually review',
    'manual_review_30day_promise': '(?i)within 30 business days',
    'chatbot_error_line': '(?im)^\\*\\*🤖 BOT\\*\\* \\[error\\]:\\s*\\[(?:ChatbotError|error)\\]',
    'greeting_only_reply_error': '(?i)Bot returned only its greeting\\s*—\\s*query was not processed',
    'session_transport_error': '(?i)SendMessage failed|No bot reply received within|AccessDeniedException|WinError \\d+',
    'truncated_bot_message': '(?im)might be a misunder$',
    'thinking_tags_leaked': '(?i)<thinking>|</thinking>|<public>',
    'duplicate_consecutive_bot_text': '(?m)^(.{15,})\\n\\n\\1$',
    'email_validation_glitch': "(?i)doesn(?:'|’)t look like an email address",
    'one_claim_at_a_time_confusion': '(?i)only process one claim at a time',
    'max_turns_reached': '(?im)^OTP fetched:[^\\n]*error=reached max_turns',
    'intent_misroute_flightstatus': '(?i)only provide flight status information for departures within the (?:next|past) 72 hours',
  },
  'bravo': {
    'intent_misroute_rebooking': 'help you rebook or change your flight',
    'generic_menu_clarifier': '§W§INFO§SINGLE_SELECT',
    'customer_forced_to_repeat': '(?s)§W§INFO§SINGLE_SELECT.*§W§INFO§SINGLE_SELECT',
    'bot_reset_case_system_outage': "§W§BANNER§I'm having trouble reaching our case system right now",
    'repeated_identity_verification': "(?s)I've sent a verification code.*I've sent a verification code",
    'otp_retry_or_timeout': '(?i)resend (?:the )?code|new verification code|code (?:has )?expired|(?:invalid|incorrect) (?:verification |one-time )?code|verification code (?:was|is) (?:invalid|incorrect|expired)|sent (?:you )?a new code',
    'duplicate_claim_already_submitted': 'claim has already been submitted on your behalf.{0,120}#CCD-\\d{7}-[A-Z0-9]{6}',
    'other_carrier_redirect': 'operated by \\*\\*[\\w .-]+\\*\\*\\.? Please reach out to',
    'star_alliance_agent_referral': 'operated by our Star Alliance partner',
    'escalation_manual_review': 'send your claim to manual review',
    'agent_review_submission': '§W§BANNER§Your case has been submitted for agent review\\.',
    'escalation_live_agent': 'connect(?:ing)? you with a live agent|1-888-247-2262',
    'forward_failure': "§W§BANNER§I couldn'?t forward this to our team just now",
    'thirty_day_promise': 'hear from a team member within 30 days',
    'dispute_canned_rebuff': 'I understand your frustration',
    'reason_template_bug': '(?:caused by|reason is:?) Your flight was disrupted',
    'time_limit_rejection': 'falls outside the time limit for submitting a compensation request',
    'inconsistent_processing_promises': '(?s)5 to 10 business days to process payment.*processed within the next 15 days',
  },
}

# validated cross-format marker: bot routed the request into FD claim intake
# (second alternative catches claim starts phrased without the intake boilerplate)
INTENT_RX = "To file your claim, you['’]?ll need your booking reference|get your flight delay compensation claim started"

# ---- canonical stage vocabulary (report rows are always this, in this order) ----
STAGE_MAP = {
  "greeting": {
    "alpha": [
      "bot_greeting"
    ],
    "bravo": [
      "greeting"
    ]
  },
  "intent_stated": {
    "alpha": [
      "customer_disruption_intent"
    ],
    "bravo": [
      "customer_intent"
    ]
  },
  "intent_recognized": {
    "alpha": [
      "__intent__"
    ],
    "bravo": [
      "__intent__"
    ]
  },
  "decision_disclosure": {
    "alpha": [
      "automated_decision_disclosure"
    ],
    "bravo": [
      "automated_decision_banner"
    ]
  },
  "identity_collection": {
    "alpha": [
      "identity_request"
    ],
    "bravo": [
      "full_name_collection",
      "booking_reference_collection"
    ]
  },
  "identity_provided": {
    "alpha": [
      "identity_provided"
    ],
    "bravo": [
      "identity_confirmation_summary"
    ]
  },
  "otp_channel_selection": {
    "alpha": [
      "otp_channel_selection",
      "otp_channel_chosen"
    ],
    "bravo": [
      "otp_channel_selection"
    ]
  },
  "otp_entered": {
    "alpha": [
      "otp_entered"
    ],
    "bravo": [
      "otp_code_entry"
    ]
  },
  "identity_verified": {
    "alpha": [
      "otp_verified"
    ],
    "bravo": [
      "identity_verified"
    ]
  },
  "booking_retrieved": {
    "alpha": [
      "otp_channel_selection"
    ],
    "bravo": [
      "booking_retrieved_trip_confirmation"
    ]
  },
  "claim_details_collection": {
    "alpha": [
      "contact_email_confirmation",
      "country_of_residence_request",
      "additional_info_and_receipts",
      "manual_contact_info_collection"
    ],
    "bravo": [
      "deposit_country_selection"
    ]
  },
  "decision_rendered": {
    "alpha": [
      "outcome_eligible_final",
      "outcome_not_eligible_final"
    ],
    "bravo": [
      "eligibility_eligible",
      "eligibility_not_eligible",
      "eligibility_no_determination",
      "adverse_decision_extra"
    ]
  },
  "amount_quoted": {
    "alpha": [
      "compensation_amount_quoted_provisional"
    ],
    "bravo": [
      "compensation_amount_quoted"
    ]
  },
  "payment_method": {
    "alpha": [
      "payment_method_collection"
    ],
    "bravo": [
      "payment_method_disclosure",
      "payment_email_confirmation"
    ]
  },
  "claim_submitted": {
    "alpha": [
      "claim_submitted"
    ],
    "bravo": [
      "claim_review_summary",
      "claim_submission_consent",
      "claim_submitted_confirmation"
    ]
  },
  "case_reference_issued": {
    "alpha": [
      "case_reference_issued"
    ],
    "bravo": [
      "case_reference_issued"
    ]
  },
  "terminal_outcome": {
    "alpha": [
      "outcome_eligible_final",
      "outcome_not_eligible_final",
      "outcome_escalated_manual_review",
      "case_reference_issued"
    ],
    "bravo": [
      "eligibility_eligible",
      "eligibility_not_eligible",
      "eligibility_no_determination",
      "adverse_decision_extra",
      "claim_submitted_confirmation",
      "case_reference_issued"
    ]
  },
  "wrapup": {
    "alpha": [
      "wrapup_anything_else",
      "survey_prompt"
    ],
    "bravo": [
      "wrap_up",
      "survey_feedback",
      "session_end"
    ]
  }
}

STAGE_ORDER = [
  "greeting",
  "intent_stated",
  "intent_recognized",
  "decision_disclosure",
  "identity_collection",
  "identity_provided",
  "otp_channel_selection",
  "otp_entered",
  "identity_verified",
  "booking_retrieved",
  "claim_details_collection",
  "decision_rendered",
  "amount_quoted",
  "payment_method",
  "claim_submitted",
  "case_reference_issued",
  "terminal_outcome",
  "wrapup"
]

STAGE_LABELS = {
  "greeting": "Bot greeting",
  "intent_stated": "Customer states disruption intent",
  "intent_recognized": "Bot routes into claim flow (intent recognized)",
  "decision_disclosure": "Automated-decision disclosure shown",
  "identity_collection": "Identity requested (name + booking ref)",
  "identity_provided": "Identity provided / confirmed",
  "otp_channel_selection": "OTP channel offered",
  "otp_entered": "OTP code entered",
  "identity_verified": "Identity verified",
  "booking_retrieved": "Booking retrieved",
  "claim_details_collection": "Claim details collected",
  "decision_rendered": "Eligibility decision rendered",
  "amount_quoted": "Compensation amount quoted",
  "payment_method": "Payment method arranged",
  "claim_submitted": "Claim submitted",
  "case_reference_issued": "Case reference issued",
  "terminal_outcome": "Any terminal outcome reached",
  "wrapup": "Wrap-up / survey"
}

ANOMALY_MAP = {
  "language_reset_dropped_query": {
    "alpha": [
      "first_query_dropped_language_reset"
    ],
    "bravo": []
  },
  "forced_repeat": {
    "alpha": [
      "customer_forced_to_repeat"
    ],
    "bravo": [
      "customer_forced_to_repeat"
    ]
  },
  "otp_trouble": {
    "alpha": [
      "otp_fetch_failure"
    ],
    "bravo": [
      "otp_retry_or_timeout",
      "repeated_identity_verification"
    ]
  },
  "booking_lookup_trouble": {
    "alpha": [
      "booking_lookup_failure",
      "booking_lookup_loop"
    ],
    "bravo": []
  },
  "intent_misroute": {
    "alpha": [
      "intent_misroute_flightstatus"
    ],
    "bravo": [
      "intent_misroute_rebooking",
      "generic_menu_clarifier"
    ]
  },
  "escalation_to_human": {
    "alpha": [
      "escalation_to_human"
    ],
    "bravo": [
      "escalation_manual_review",
      "agent_review_submission",
      "escalation_live_agent"
    ]
  },
  "manual_review_promise": {
    "alpha": [
      "manual_review_30day_promise"
    ],
    "bravo": [
      "thirty_day_promise"
    ]
  },
  "duplicate_claim_block": {
    "alpha": [
      "one_claim_at_a_time_confusion"
    ],
    "bravo": [
      "duplicate_claim_already_submitted"
    ]
  },
  "carrier_redirect": {
    "alpha": [],
    "bravo": [
      "other_carrier_redirect",
      "star_alliance_agent_referral"
    ]
  },
  "bot_output_glitch": {
    "alpha": [
      "truncated_bot_message",
      "thinking_tags_leaked",
      "duplicate_consecutive_bot_text",
      "email_validation_glitch"
    ],
    "bravo": [
      "reason_template_bug",
      "dispute_canned_rebuff",
      "forward_failure",
      "inconsistent_processing_promises"
    ]
  },
  "bot_reset": {
    "alpha": [],
    "bravo": [
      "bot_reset_case_system_outage"
    ]
  },
  "time_limit_rejection": {
    "alpha": [],
    "bravo": [
      "time_limit_rejection"
    ]
  }
}

ANOMALY_LABELS = {
  "language_reset_dropped_query": "Language reset dropped first query",
  "forced_repeat": "Customer forced to repeat info",
  "otp_trouble": "OTP retry / timeout trouble",
  "booking_lookup_trouble": "Booking lookup failure / loop",
  "intent_misroute": "Intent misroute / menu detour",
  "escalation_to_human": "Escalated to human / manual review",
  "manual_review_promise": "Manual-review turnaround promised",
  "duplicate_claim_block": "Blocked by existing/duplicate claim",
  "carrier_redirect": "Redirected to another carrier",
  "bot_output_glitch": "Bot output glitch (template/truncation)",
  "bot_reset": "Bot reset mid-flow",
  "time_limit_rejection": "Rejected on filing time limit"
}

# stages a scenario is EXPECTED to reach, used for the trajectory match score
TRAJECTORY_BASE = [
  'greeting', 'intent_stated', 'intent_recognized', 'decision_disclosure',
  'identity_collection', 'identity_provided', 'otp_channel_selection',
  'otp_entered', 'identity_verified', 'booking_retrieved', 'decision_rendered',
]
TRAJECTORY_ELIGIBLE_EXTRA = ['amount_quoted', 'claim_submitted', 'case_reference_issued']
TRAJECTORY_PAY_EXTRA = ['payment_method']


def expected_stages(record):
    exp = list(TRAJECTORY_BASE)
    if record.get('expected_status') == 'ELIGIBLE':
        exp += TRAJECTORY_ELIGIBLE_EXTRA
    if record.get('family') == 'PAY':
        exp += TRAJECTORY_PAY_EXTRA
    return exp


# ---- canonical check-name taxonomy (LLM-generated names -> fixed keys) ----
_CHECKS = [
    ('currency', re.compile('currency', re.I)),
    ('eligibility_status', re.compile('eligibility', re.I)),
    ('compensation_amount', re.compile('compensation\\s+amount', re.I)),
    ('system_code', re.compile('system\\s+code', re.I)),
    ('pnr_match', re.compile('\\bpnr\\b', re.I)),
    ('passenger_name', re.compile('^passenger', re.I)),
    ('regime', re.compile('regime', re.I)),
    ('booking_retrieval', re.compile('^booking', re.I)),
    ('completion', re.compile('claim|final\\s+outcome|automated\\s+decision|immediate', re.I)),
]


def canonicalize_check(raw_name):
    for key, rx in _CHECKS:
        if rx.search(raw_name or ''):
            return key
    return 'other'


# ---- harness error buckets; fatal=False means the flow itself completed ----
_ERROR_BUCKETS = [
    ('end_probe_greeting_only', re.compile('^Bot returned only its greeting'), False),
    ('max_turns_exhausted', re.compile('^reached max_turns$'), True),
    ('otp_fetch_failure', re.compile('^No Mailinator OTP'), True),
    ('bot_reply_timeout', re.compile('^No bot reply received within \\d+s'), True),
    ('send_access_denied', re.compile('^SendMessage failed:.*AccessDeniedException'), True),
]


def bucket_error(err):
    """-> (bucket_key, fatal). (None, False) when there was no error."""
    if not err:
        return None, False
    for key, rx, fatal in _ERROR_BUCKETS:
        if rx.search(err):
            return key, fatal
    return 'other_error', True
