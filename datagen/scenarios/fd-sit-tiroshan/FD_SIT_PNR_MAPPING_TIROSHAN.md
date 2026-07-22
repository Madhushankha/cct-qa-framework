# FD SIT Test Case to PNR Mapping - Tiroshan

**Environment:** INT (982081066747)
**OTP Email:** tiroshanmbck@gmail.com
**Total PNRs:** 132
**Flight Date:** 2026-06-26
**PNR Prefix:** ZFE

## Quick Reference

To test: Enter **PNR** + **Last Name** in chatbot.

---

| SIT ID | PNR | Last Name | Route | Scenario | Regime | Outcome |
|--------|-----|-----------|-------|----------|--------|---------|
| FD-SIT-001 | ZFE001 | THOMPSON | YYZ→YVR | APPR 3-6hr delay CAD 400... | APPR | Eligible |
| FD-SIT-002 | ZFE002 | CHEN | YUL→YYZ | APPR 3-6hr AC Wallet... | APPR | Eligible |
| FD-SIT-003 | ZFE003 | WILLIAMS | YVR→YUL | APPR 6-9hr delay CAD 700... | APPR | Eligible |
| FD-SIT-004 | ZFE004 | HARRISON | YYC→YOW | APPR 6-9hr AC Wallet... | APPR | Eligible |
| FD-SIT-005 | ZFE005 | DUBOIS | YEG→YHZ | APPR 9hr+ delay CAD 1000... | APPR | Eligible |
| FD-SIT-006 | ZFE006 | COHEN | YYZ→YVR | APPR 9hr+ AC Wallet... | APPR | Eligible |
| FD-SIT-007 | ZFE007 | JOHNSON | YUL→YYZ | APPR VOL/INVOL promise... | APPR | Eligible |
| FD-SIT-008 | ZFE008 | MARTIN | LHR→YYZ | EU/UK 261 UK 3-4hr GBP 260... | EU/UK 261 | Eligible |
| FD-SIT-009 | ZFE009 | BROWN | LGW→YUL | EU/UK 261 UK 4hr+ GBP 520... | EU/UK 261 | Eligible |
| FD-SIT-010 | ZFE010 | TAYLOR | CDG→YUL | EU 261 EUR 3-4hr EUR 300... | EU/UK 261 | Eligible |
| FD-SIT-011 | ZFE011 | ANDERSON | FRA→YYZ | EU 261 EUR 4hr+ EUR 600... | EU/UK 261 | Eligible |
| FD-SIT-012 | ZFE012 | THOMAS | AMS→YVR | EU 261 short/medium haul... | EU/UK 261 | Eligible |
| FD-SIT-013 | ZFE013 | JACKSON | PTP→YUL | EU 261 DOM-TOM Guadeloupe... | EU/UK 261 | Eligible |
| FD-SIT-014 | ZFE014 | WHITE | TLV→YYZ | ASL Israel 480min+... | ASL | Eligible |
| FD-SIT-015 | ZFE015 | HARRIS | YVR→YUL | APPR multi-pax aggregated... | APPR | Eligible |
| FD-SIT-016 | ZFE016 | ROBINSON | YYC→YOW | APPR group individual claim... | APPR | Eligible |
| FD-SIT-017 | ZFE017 | WALKER | YEG→YHZ | APPR no-travel controllable... | APPR | Eligible |
| FD-SIT-018 | ZFE018 | HALL | MAN→YVR | EU/UK no-travel controllable... | EU/UK 261 | Eligible |
| FD-SIT-019 | ZFE019 | ALLEN | TLV→YYZ | ASL no-travel controllable... | ASL | Eligible |
| FD-SIT-020 | ZFE020 | YOUNG | LHR→YYZ | Mixed APPR+EU most generous... | EU/UK 261 | Eligible |
| FD-SIT-021 | ZFE021 | KING | FCO→YYZ | Mixed FX conversion... | EU/UK 261 | Eligible |
| FD-SIT-022 | ZFE022 | WRIGHT | TLV→YYZ | Mixed APPR+ASL... | ASL | Eligible |
| FD-SIT-023 | ZFE023 | SCOTT | LGW→YUL | Mixed regime expired fallback... | EU/UK 261 | Eligible |
| FD-SIT-024 | ZFE024 | GREEN | YYZ→YVR | Not eligible below threshold accept... | APPR | Not Eligible |
| FD-SIT-025 | ZFE025 | BAKER | YUL→YYZ | Not eligible below threshold dispute... | APPR | Not Eligible |
| FD-SIT-026 | ZFE026 | ADAMS | YVR→YUL | Not eligible uncontrollable... | APPR | Not Eligible |
| FD-SIT-028 | ZFE028 | NELSON | YYC→YOW | Not eligible employee... | APPR | Not Eligible |
| FD-SIT-029 | ZFE029 | HILL | YEG→YHZ | Not eligible infant... | APPR | Not Eligible |
| FD-SIT-030 | ZFE030 | RAMIREZ | YYZ→YVR | Not eligible 15+ days before... | APPR | Not Eligible |
| FD-SIT-031 | ZFE031 | CAMPBELL | YUL→YYZ | Not eligible denied boarding... | APPR | Not Eligible |
| FD-SIT-032 | ZFE032 | MITCHELL | YVR→YUL | Not eligible limitation period... | APPR | Not Eligible |
| FD-SIT-033 | ZFE033 | ROBERTS | YYZ→JFK | Not eligible all-OAL... | OAL | Not Eligible |
| FD-SIT-035 | ZFE035 | CARTER | YYC→YOW | Not eligible flight operated... | APPR | Not Eligible |
| FD-SIT-036 | ZFE036 | PHILLIPS | YEG→YHZ | Not eligible MSL below threshold... | APPR | Not Eligible |
| FD-SIT-037 | ZFE037 | EVANS | YYZ→JFK | No determination OAL redirect... | OAL | No Determ |
| FD-SIT-038 | ZFE038 | TURNER | YYZ→JFK | No determination Star Alliance... | OAL | No Determ |
| FD-SIT-039 | ZFE039 | TORRES | YYZ→YVR | No determination new destination... | APPR | No Determ |
| FD-SIT-040 | ZFE040 | PARKER | YUL→YYZ | No determination 14-day polling... | APPR | No Determ |
| FD-SIT-041 | ZFE041 | COLLINS | YVR→YUL | No determination MSL/OAL missing... | APPR | No Determ |
| FD-SIT-042 | ZFE042 | EDWARDS | YYC→YOW | Pending 72hr wait window... | APPR | Pending |
| FD-SIT-043 | ZFE043 | STEWART | YEG→YHZ | Welcome back eligible... | APPR | Pending |
| FD-SIT-044 | ZFE044 | SANCHEZ | YYZ→YVR | Welcome back not eligible... | APPR | Not Eligible |
| FD-SIT-045 | ZFE045 | MORRIS | YUL→YYZ | ID exchanged tickets... | APPR | Eligible |
| FD-SIT-046 | ZFE046 | ROGERS | YVR→YUL | Aeroplan bypasses OTP... | APPR | Eligible |
| FD-SIT-047 | ZFE047 | REED | YYC→YOW | Aeroplan e-ticket xref... | APPR | Eligible |
| FD-SIT-048 | ZFE048 | COOK | YEG→YHZ | No ID match shell case... | APPR | Manual |
| FD-SIT-049 | ZFE049 | MORGAN | YYZ→YVR | OTP fail IDV fallback... | APPR | Eligible |
| FD-SIT-050 | ZFE050 | BELL | YUL→YYZ | OTP and IDV fail... | APPR | Eligible |
| FD-SIT-051 | ZFE051 | MURPHY | YVR→YUL | OTP service unavailable... | APPR | Eligible |
| FD-SIT-052 | ZFE052 | BAILEY | YYC→YOW | Payment IDV fail fraud... | APPR | Fraud |
| FD-SIT-053 | ZFE053 | RIVERA | YEG→YHZ | Travel agency OTP NOA... | APPR | Eligible |
| FD-SIT-054 | ZFE054 | COOPER | YYZ→YVR | Ambiguous intent disambiguation... | APPR | Eligible |
| FD-SIT-055 | ZFE055 | RICHARDSON | YUL→YYZ | FAQ then claim switch... | APPR | Eligible |
| FD-SIT-056 | ZFE056 | COX | YVR→YUL | Multiple intents priority... | APPR | Eligible |
| FD-SIT-057 | ZFE057 | HOWARD | YYC→YOW | Interac cash payout... | APPR | Eligible |
| FD-SIT-058 | ZFE058 | WARD | YYZ→LAX | IBM BSM HSBC payout... | APPR | Eligible |
| FD-SIT-059 | ZFE059 | TORRES | YUL→MIA | EFT WL Paycycle payout... | APPR | Eligible |
| FD-SIT-060 | ZFE060 | PETERSON | YEG→YHZ | Cheque payout... | APPR | Eligible |
| FD-SIT-061 | ZFE061 | GRAY | YYZ→YVR | AC Wallet batch fallback... | APPR | Eligible |
| FD-SIT-063 | ZFE063 | RAMIREZ | YUL→YYZ | Promo code compensation... | APPR | Eligible |
| FD-SIT-064 | ZFE064 | JAMES | YVR→SFO | Country payment mapping... | APPR | Eligible |
| FD-SIT-065 | ZFE065 | WATSON | YVR→YUL | AC Wallet frozen fallback... | APPR | Eligible |
| FD-SIT-066 | ZFE066 | BROOKS | YYC→YOW | IBM retry then manual... | APPR | Eligible |
| FD-SIT-067 | ZFE067 | KELLY | YEG→YHZ | Payment callback mismatch... | APPR | Eligible |
| FD-SIT-068 | ZFE068 | SANDERS | YYZ→LAX | Unsupported payout country... | APPR | Eligible |
| FD-SIT-069 | ZFE069 | PRICE | YYZ→YVR | Country residence missing... | APPR | Eligible |
| FD-SIT-070 | ZFE070 | BENNETT | YUL→YYZ | Youth passenger manual... | APPR | Eligible |
| FD-SIT-071 | ZFE071 | WOOD | YVR→YUL | UMNR passenger manual... | APPR | Eligible |
| FD-SIT-072 | ZFE072 | BARNES | YYC→YOW | Split PNR group treatment... | APPR | Eligible |
| FD-SIT-074 | ZFE074 | ROSS | YEG→YHZ | CyberSource YELLOW... | APPR | Fraud |
| FD-SIT-075 | ZFE075 | HENDERSON | YYZ→YVR | CyberSource RED no dispute... | APPR | Fraud |
| FD-SIT-076 | ZFE076 | COLEMAN | YUL→YYZ | CyberSource RED dispute... | APPR | Fraud |
| FD-SIT-077 | ZFE077 | JENKINS | YVR→YUL | CyberSource unavailable... | APPR | Fraud |
| FD-SIT-078 | ZFE078 | PERRY | YYC→YOW | RDS flag overrides GREEN... | APPR | Fraud |
| FD-SIT-079 | ZFE079 | POWELL | YEG→YHZ | Duplicate at eligibility... | APPR | Duplicate |
| FD-SIT-080 | ZFE080 | LONG | YYZ→YVR | Duplicate at preauth... | APPR | Duplicate |
| FD-SIT-081 | ZFE081 | PATTERSON | YUL→YYZ | No duplicate overlap... | APPR | Duplicate |
| FD-SIT-083 | ZFE083 | HUGHES | YVR→YUL | Resume token invalid... | APPR | Error |
| FD-SIT-084 | ZFE084 | FLORES | YYC→YOW | Due-task case load fail... | APPR | Error |
| FD-SIT-085 | ZFE085 | WASHINGTON | YEG→YHZ | Service downtime retry... | APPR | Error |
| FD-SIT-086 | ZFE086 | BUTLER | YYZ→YVR | Session expiration resume... | APPR | Error |
| FD-SIT-087 | ZFE087 | SIMMONS | YUL→YYZ | Case Management unavailable... | APPR | Error |
| FD-SIT-090 | ZFE090 | FOSTER | YVR→YUL | Finalize replay once... | APPR | Error |
| FD-SIT-091 | ZFE091 | GONZALES | YYC→YOW | Eligibility malformed... | APPR | Error |
| FD-SIT-092 | ZFE092 | BRYANT | YEG→YHZ | Notification failure no dup... | APPR | Eligible |
| FD-SIT-093 | ZFE093 | ALEXANDER | MAD→YUL | Foreign currency CAD log... | EU/UK 261 | Eligible |
| FD-SIT-094 | ZFE094 | RUSSELL | YYZ→YVR | Claims company CA/US blocked... | APPR | Third-Party |
| FD-SIT-095 | ZFE095 | GRIFFIN | CDG→YUL | Claims company EU manual... | EU/UK 261 | Third-Party |
| FD-SIT-096 | ZFE096 | DIAZ | YUL→YYZ | Travel agency NOA... | APPR | Third-Party |
| FD-SIT-097 | ZFE097 | HAYES | YVR→YUL | Guardian manual... | APPR | Third-Party |
| FD-SIT-098 | ZFE098 | MYERS | YYC→YOW | Missing authority manual... | APPR | Third-Party |
| FD-SIT-099 | ZFE099 | FORD | YEG→YHZ | Existing case branch... | APPR | Third-Party |
| FD-SIT-100 | ZFE100 | HAMILTON | YYZ→YVR | WhatsApp rich fallback... | APPR | Channel |
| FD-SIT-101 | ZFE101 | GRAHAM | YUL→YYZ | Mobile web responsive... | APPR | Channel |
| FD-SIT-102 | ZFE102 | SULLIVAN | YVR→YUL | Unsupported language... | APPR | Channel |
| FD-SIT-103 | ZFE103 | WALLACE | YYC→YOW | Max chat duration... | APPR | Channel |
| FD-SIT-104 | ZFE104 | WOODS | YEG→YHZ | Negative sentiment handoff... | APPR | Channel |
| FD-SIT-105 | ZFE105 | WEST | YYZ→YVR | Dispute not eligible... | APPR | Dispute |
| FD-SIT-106 | ZFE106 | COLE | YUL→YYZ | Banking error retry... | APPR | Eligible |
| FD-SIT-107 | ZFE107 | HUNT | YVR→YUL | Multi-segment display... | APPR | Eligible |
| FD-SIT-108 | ZFE108 | MENDEZ | YYC→YOW | IROP changed itinerary... | APPR | Eligible |
| FD-SIT-109 | ZFE109 | SCHMIDT | YEG→YHZ | Multi-select both bounds... | APPR | Eligible |
| FD-SIT-110 | ZFE110 | HARRISON | YYZ→YVR | Neither selection no-match... | APPR | Eligible |
| FD-SIT-111 | ZFE111 | SNYDER | YUL→YYZ | Segment correction... | APPR | Eligible |
| FD-SIT-113 | ZFE113 | SIMPSON | YVR→YUL | Duplicate by other disputed... | APPR | Duplicate |
| FD-SIT-115 | ZFE115 | DUNCAN | YYC→YOW | Claim within 72h queued... | APPR | Eligible |
| FD-SIT-116 | ZFE116 | HENDERSON | YEG→YHZ | Claim after window... | APPR | Eligible |
| FD-SIT-117 | ZFE117 | GRAHAM | YYZ→YVR | Case status waiting... | APPR | Eligible |
| FD-SIT-119 | ZFE119 | CRUZ | YUL→YYZ | French language... | APPR | Eligible |
| FD-SIT-121 | ZFE121 | SHAW | YVR→YUL | Appeal closed case... | APPR | Eligible |
| FD-SIT-122 | ZFE122 | BLACK | YYC→YOW | Intent change after eligibility... | APPR | Eligible |
| FD-SIT-123 | ZFE123 | PIERCE | YEG→YHZ | Appeal after next intent... | APPR | Eligible |
| FD-SIT-124 | ZFE124 | OLSON | YYZ→YVR | Claims company no attachment... | APPR | Third-Party |
| FD-SIT-125 | ZFE125 | WARREN | YUL→YYZ | Language change mid-convo... | APPR | Eligible |
| FD-SIT-126 | ZFE126 | AUSTIN | FRA→YYZ | Dispute currency conversion... | EU/UK 261 | Eligible |
| FD-SIT-127 | ZFE127 | STONE | YVR→YUL | Proactive case duplicate... | APPR | Duplicate |
| FD-SIT-128 | ZFE128 | HART | YYC→YOW | Misspelled first name... | APPR | Eligible |
| FD-SIT-129 | ZFE129 | MILLS | YEG→YHZ | Second dispute... | APPR | Dispute |
| FD-SIT-130 | ZFE130 | WAGNER | YYZ→YVR | Dispute alt email... | APPR | Dispute |
| FD-SIT-131 | ZFE131 | FORD | YUL→YYZ | Dispute speak person... | APPR | Dispute |
| FD-SIT-132 | ZFE132 | WELLS | YVR→YUL | Multipax permission no... | APPR | Eligible |
| FD-SIT-133 | ZFE133 | SIMPSON | YYC→YOW | Multipax no own claim... | APPR | Eligible |
| FD-SIT-134 | ZFE134 | TUCKER | YEG→YHZ | Multipax duplicate permission... | APPR | Eligible |
| FD-SIT-135 | ZFE135 | HUNTER | YYZ→YVR | Remove self duplicate... | APPR | Duplicate |
| FD-SIT-136 | ZFE136 | HICKS | YUL→YYZ | Continue triage... | APPR | Duplicate |
| FD-SIT-137 | ZFE137 | CRAWFORD | YVR→YUL | Duplicate by other... | APPR | Duplicate |
| FD-SIT-138 | ZFE138 | BOYD | YYC→YOW | Empathy triggered... | APPR | Eligible |
| FD-SIT-139 | ZFE139 | MASON | YEG→YHZ | Case status action needed... | APPR | Eligible |
| FD-SIT-140 | ZFE140 | THOMPSON | YYZ→YVR | Crude language... | APPR | Eligible |
| FD-SIT-141 | ZFE141 | CHEN | YUL→YYZ | Legal action threat... | APPR | Eligible |
| FD-SIT-142 | ZFE142 | WILLIAMS | YVR→YUL | Wrong Aeroplan ACW... | APPR | Eligible |
| FD-SIT-144 | ZFE144 | HARRISON | YYC→YOW | Compensation outages... | APPR | Error |