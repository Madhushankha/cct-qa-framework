# FD SIT Test Case to PNR Mapping

**Environment:** INT (982081066747)  
**OTP Email:** chathuranga.viraj.qa@gmail.com  
**Total PNRs:** 132  
**Flight Date:** 2026-06-25  

## Quick Reference

To test: Enter **PNR** + **Last Name** in chatbot.

---

## Eligible - Travel Completed (16)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-001 | ZFD001 | THOMPSON | YYZ→YVR | APPR 3-6hr delay | CAD 400 cash |
| FD-SIT-002 | ZFD002 | CHEN | YUL→YYZ | APPR 3-6hr AC Wallet | CAD 480 wallet |
| FD-SIT-003 | ZFD003 | WILLIAMS | YVR→YUL | APPR 6-9hr delay | CAD 700 cash |
| FD-SIT-004 | ZFD004 | HARRISON | YYC→YOW | APPR 6-9hr AC Wallet | CAD 840 wallet |
| FD-SIT-005 | ZFD005 | DUBOIS | YEG→YHZ | APPR 9hr+ delay | CAD 1,000 cash |
| FD-SIT-006 | ZFD006 | COHEN | YYZ→YVR | APPR 9hr+ AC Wallet | CAD 1,200 wallet |
| FD-SIT-007 | ZFD007 | JOHNSON | YUL→YYZ | APPR VOL/INVOL promise | Promise calc |
| FD-SIT-008 | ZFD008 | MARTIN | LHR→YYZ | EU/UK 261 UK 3-4hr | GBP 260 |
| FD-SIT-009 | ZFD009 | BROWN | LGW→YUL | EU/UK 261 UK 4hr+ | GBP 520 |
| FD-SIT-010 | ZFD010 | TAYLOR | CDG→YUL | EU 261 EUR 3-4hr | EUR 300 |
| FD-SIT-011 | ZFD011 | ANDERSON | FRA→YYZ | EU 261 EUR 4hr+ | EUR 600 |
| FD-SIT-012 | ZFD012 | THOMAS | AMS→YVR | EU 261 short/medium | EUR 250/400 |
| FD-SIT-013 | ZFD013 | JACKSON | PTP→YUL | EU 261 DOM-TOM | EUR 400 flat |
| FD-SIT-014 | ZFD014 | WHITE | TLV→YYZ | ASL Israel 480min+ | ILS 3,580 |
| FD-SIT-015 | ZFD015 | HARRIS | YVR→YUL | Multi-pax (3 pax) | Aggregated payout |
| FD-SIT-016 | ZFD016 | ROBINSON | YYC→YOW | Group booking | Individual claim |

## Eligible - No Travel (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-017 | ZFD017 | WALKER | YEG→YHZ | APPR no-travel controllable | Compensation |
| FD-SIT-018 | ZFD018 | HALL | MAN→YVR | EU/UK no-travel controllable | Compensation |
| FD-SIT-019 | ZFD019 | ALLEN | TLV→YYZ | ASL no-travel controllable | Compensation |

## Mixed Regime (4)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-020 | ZFD020 | YOUNG | LHR→YYZ | APPR + EU/UK 261 | Most generous |
| FD-SIT-021 | ZFD021 | KING | FCO→YYZ | Bank of Canada FX | FX conversion |
| FD-SIT-022 | ZFD022 | WRIGHT | TLV→YYZ | APPR + ASL | Most generous |
| FD-SIT-023 | ZFD023 | SCOTT | LGW→YUL | Regime expired fallback | Fallback regime |

## Not Eligible (11)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-024 | ZFD024 | GREEN | YYZ→YVR | Below threshold - accept | Not eligible |
| FD-SIT-025 | ZFD025 | BAKER | YUL→YYZ | Below threshold - dispute | Not eligible |
| FD-SIT-026 | ZFD026 | ADAMS | YVR→YUL | Uncontrollable | Not eligible |
| FD-SIT-028 | ZFD028 | NELSON | YYC→YOW | Employee/non-revenue | Not eligible |
| FD-SIT-029 | ZFD029 | HILL | YEG→YHZ | Infant without seat | Adult eligible |
| FD-SIT-030 | ZFD030 | RAMIREZ | YYZ→YVR | Change 15+ days before | Not eligible |
| FD-SIT-031 | ZFD031 | CAMPBELL | YUL→YYZ | Denied boarding | Not eligible |
| FD-SIT-032 | ZFD032 | MITCHELL | YVR→YUL | Outside limitation | Not eligible |
| FD-SIT-033 | ZFD033 | ROBERTS | YYZ→JFK | All-OAL itinerary | Redirect to OAL |
| FD-SIT-035 | ZFD035 | CARTER | YYC→YOW | Flight operated | Not eligible |
| FD-SIT-036 | ZFD036 | PHILLIPS | YEG→YHZ | MSL below threshold | Not eligible |

## No Determination & Pending (8)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-037 | ZFD037 | EVANS | YYZ→JFK | OAL redirect | Redirect |
| FD-SIT-038 | ZFD038 | TURNER | YYZ→JFK | Star Alliance - StarQuest | StarQuest |
| FD-SIT-039 | ZFD039 | TORRES | YYZ→YVR | New destination | No determination |
| FD-SIT-040 | ZFD040 | PARKER | YUL→YYZ | 14-day polling | No determination |
| FD-SIT-041 | ZFD041 | COLLINS | YVR→YUL | MSL/OAL missing | No determination |
| FD-SIT-042 | ZFD042 | EDWARDS | YYC→YOW | 72hr wait window | Pending → queue |
| FD-SIT-043 | ZFD043 | STEWART | YEG→YHZ | Welcome back eligible | Eligible |
| FD-SIT-044 | ZFD044 | SANCHEZ | YYZ→YVR | Welcome back not eligible | Not eligible |

## Identification & Authentication (9)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-045 | ZFD045 | MORRIS | YUL→YYZ | Exchanged tickets | ID success |
| FD-SIT-046 | ZFD046 | ROGERS | YVR→YUL | Aeroplan bypasses OTP | No OTP needed |
| FD-SIT-047 | ZFD047 | REED | YYC→YOW | Aeroplan e-ticket xref | PNR resolved |
| FD-SIT-048 | ZFD048 | COOK | YEG→YHZ | No ID match | Shell case |
| FD-SIT-049 | ZFD049 | MORGAN | YYZ→YVR | OTP fail, IDV success | IDV fallback |
| FD-SIT-050 | ZFD050 | BELL | YUL→YYZ | OTP + IDV fail | End flow |
| FD-SIT-051 | ZFD051 | MURPHY | YVR→YUL | OTP unavailable | Error |
| FD-SIT-052 | ZFD052 | BAILEY | YYC→YOW | Payment IDV fail | Fraud flag |
| FD-SIT-053 | ZFD053 | RIVERA | YEG→YHZ | Travel agency OTP | Manual |

## Intent & Conversation (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-054 | ZFD054 | COOPER | YYZ→YVR | Ambiguous intent | Disambiguation |
| FD-SIT-055 | ZFD055 | RICHARDSON | YUL→YYZ | FAQ then claim | Context switch |
| FD-SIT-056 | ZFD056 | COX | YVR→YUL | Multiple intents | FD prioritized |

## Payment & Country (12)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-057 | ZFD057 | HOWARD | YYC→YOW | Interac cash | Interac accepted |
| FD-SIT-058 | ZFD058 | WARD | YYZ→LAX | IBM/BSM/HSBC | Payout accepted |
| FD-SIT-059 | ZFD059 | TORRES | YUL→MIA | EFT/WL Paycycle | Bank details |
| FD-SIT-060 | ZFD060 | PETERSON | YEG→YHZ | Cheque payout | Manual if no addr |
| FD-SIT-061 | ZFD061 | GRAY | YYZ→YVR | AC Wallet batch | Cash fallback |
| FD-SIT-063 | ZFD063 | RAMIREZ | YUL→YYZ | Promo code | Inventory reserved |
| FD-SIT-064 | ZFD064 | JAMES | YVR→SFO | Country mapping | EFT/Wire/Interac |
| FD-SIT-065 | ZFD065 | WATSON | YVR→YUL | AC Wallet frozen | Cash fallback |
| FD-SIT-066 | ZFD066 | BROOKS | YYC→YOW | IBM retry | Retry/manual |
| FD-SIT-067 | ZFD067 | KELLY | YEG→YHZ | Callback mismatch | No side effect |
| FD-SIT-068 | ZFD068 | SANDERS | YYZ→LAX | Unsupported country | Manual |
| FD-SIT-069 | ZFD069 | PRICE | YYZ→YVR | Missing country | Correct preauth |

## Passenger & Booking (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-070 | ZFD070 | BENNETT | YUL→YYZ | Youth passenger | Manual review |
| FD-SIT-071 | ZFD071 | WOOD | YVR→YUL | UMNR passenger | Manual review |
| FD-SIT-072 | ZFD072 | BARNES | YYC→YOW | Split-from-group PNR | Group treatment |

## Fraud Screening (5)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-074 | ZFD074 | ROSS | YEG→YHZ | CyberSource YELLOW | Manual queue |
| FD-SIT-075 | ZFD075 | HENDERSON | YYZ→YVR | CyberSource RED | Rejection email |
| FD-SIT-076 | ZFD076 | COLEMAN | YUL→YYZ | CyberSource RED + dispute | Manual |
| FD-SIT-077 | ZFD077 | JENKINS | YVR→YUL | CyberSource unavailable | Fail closed |
| FD-SIT-078 | ZFD078 | PERRY | YYC→YOW | RDS flag overrides | Manual review |

## Duplicate Detection (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-079 | ZFD079 | POWELL | YEG→YHZ | Duplicate at eligibility | End flow |
| FD-SIT-080 | ZFD080 | LONG | YYZ→YVR | Duplicate at preauth | Controlled |
| FD-SIT-081 | ZFD081 | PATTERSON | YUL→YYZ | No duplicate overlap | Continue |

## Wait-Window & Resilience (4)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-083 | ZFD083 | HUGHES | YVR→YUL | Resume token invalid | End flow |
| FD-SIT-084 | ZFD084 | FLORES | YYC→YOW | Due-task case fail | Manual/retry |
| FD-SIT-085 | ZFD085 | WASHINGTON | YEG→YHZ | Service downtime | Case for retry |
| FD-SIT-086 | ZFD086 | BUTLER | YYZ→YVR | Session expiration | Resume/restart |

## Case Management & Integrity (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-087 | ZFD087 | SIMMONS | YUL→YYZ | Case Mgmt unavailable | Return later |
| FD-SIT-090 | ZFD090 | FOSTER | YVR→YUL | Finalize replay | Queued once |
| FD-SIT-091 | ZFD091 | GONZALES | YYC→YOW | Eligibility malformed | Manual |

## Notification & Reporting (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-092 | ZFD092 | BRYANT | YEG→YHZ | Notification failure | No dup payment |
| FD-SIT-093 | ZFD093 | ALEXANDER | MAD→YUL | Foreign currency | CAD logged |

## Third-Party (6)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-094 | ZFD094 | RUSSELL | YYZ→YVR | Claims company CA/US | Blocked |
| FD-SIT-095 | ZFD095 | GRIFFIN | CDG→YUL | Claims company EU | Manual |
| FD-SIT-096 | ZFD096 | DIAZ | YUL→YYZ | Travel agency | NOA required |
| FD-SIT-097 | ZFD097 | HAYES | YVR→YUL | Guardian/tutor | Manual |
| FD-SIT-098 | ZFD098 | MYERS | YYC→YOW | Missing authority | Manual |
| FD-SIT-099 | ZFD099 | FORD | YEG→YHZ | Existing case | Branch handling |

## Channel & Accessibility (5)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-100 | ZFD100 | HAMILTON | YYZ→YVR | WhatsApp rich | Text fallback |
| FD-SIT-101 | ZFD101 | GRAHAM | YUL→YYZ | Mobile web | Responsive |
| FD-SIT-102 | ZFD102 | SULLIVAN | YVR→YUL | Unsupported language | Support path |
| FD-SIT-103 | ZFD103 | WALLACE | YYC→YOW | Max chat duration | Controlled |
| FD-SIT-104 | ZFD104 | WOODS | YEG→YHZ | Negative sentiment | Agent handoff |

## Claims Dashboard (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-105 | ZFD105 | WEST | YYZ→YVR | Dispute not-eligible | Linked case |
| FD-SIT-106 | ZFD106 | COLE | YUL→YYZ | Banking error | Re-process |

## Agentic Display (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-107 | ZFD107 | HUNT | YVR→YUL | Multi-segment | Display |
| FD-SIT-108 | ZFD108 | MENDEZ | YYC→YOW | IROP changed | Display |

## Journey Selection (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-109 | ZFD109 | SCHMIDT | YEG→YHZ | Both bounds | Multi-select |
| FD-SIT-110 | ZFD110 | HARRISON | YYZ→YVR | Neither selected | No-match |

## Segment Selection (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-111 | ZFD111 | SNYDER | YUL→YYZ | Segment correction | No-match |

## Duplicate / Fraud (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-113 | ZFD113 | SIMPSON | YVR→YUL | Duplicate by other | Disputed |

## Timeframe (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-115 | ZFD115 | DUNCAN | YYC→YOW | Within 72h | Queued |
| FD-SIT-116 | ZFD116 | HENDERSON | YEG→YHZ | After window (>1yr) | Not eligible |

## Case Status (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-117 | ZFD117 | GRAHAM | YYZ→YVR | Waiting for comp | Status shown |

## Language (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-119 | ZFD119 | CRUZ | YUL→YYZ | French language | French support |
| FD-SIT-125 | ZFD125 | WARREN | YUL→YYZ | Language mid-change | Switch handled |

## Appeal (2)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-121 | ZFD121 | SHAW | YVR→YUL | Appeal closed case | Appeal flow |
| FD-SIT-123 | ZFD123 | PIERCE | YEG→YHZ | Appeal after next intent | Appeal flow |

## Multi-Intent (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-122 | ZFD122 | BLACK | YYC→YOW | Intent change after elig | Next intent |

## Third Party (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-124 | ZFD124 | OLSON | YYZ→YVR | Claims co no attachment | Document needed |

## Amount / Currency (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-126 | ZFD126 | AUSTIN | FRA→YYZ | Currency dispute | Dispute flow |

## Duplicate / Proactive Case (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-127 | ZFD127 | STONE | YVR→YUL | Proactive case found | Duplicate |

## Identification (1)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-128 | ZFD128 | HART | YYC→YOW | Misspelled first name | No-match |

## Dispute (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-129 | ZFD129 | MILLS | YEG→YHZ | Second dispute | Dispute flow |
| FD-SIT-130 | ZFD130 | WAGNER | YYZ→YVR | Alt email for dispute | Manual |
| FD-SIT-131 | ZFD131 | FORD | YUL→YYZ | Speak with person | Manual |

## Multi-Pax (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-132 | ZFD132 | WELLS | YVR→YUL | Permission No | Permission flow |
| FD-SIT-133 | ZFD133 | SIMPSON | YYC→YOW | No own claim | Permission flow |
| FD-SIT-134 | ZFD134 | TUCKER | YEG→YHZ | Duplicate permission | Permission flow |

## Duplicate (3)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-135 | ZFD135 | HUNTER | YYZ→YVR | Remove self | Open own |
| FD-SIT-136 | ZFD136 | HICKS | YUL→YYZ | Continue triage | Payment flow |
| FD-SIT-137 | ZFD137 | CRAWFORD | YVR→YUL | Opened by other | Duplicate |

## Miscellaneous (6)

| SIT ID | PNR | Last Name | Route | Scenario | Expected |
|--------|-----|-----------|-------|----------|----------|
| FD-SIT-138 | ZFD138 | BOYD | YYC→YOW | Empathy triggered | Empathy flow |
| FD-SIT-139 | ZFD139 | MASON | YEG→YHZ | Action needed status | Status shown |
| FD-SIT-140 | ZFD140 | THOMPSON | YYZ→YVR | Crude language | Handled |
| FD-SIT-141 | ZFD141 | CHEN | YUL→YYZ | Legal action threat | Handled |
| FD-SIT-142 | ZFD142 | WILLIAMS | YVR→YUL | Wrong Aeroplan for ACW | Handled |
| FD-SIT-144 | ZFD144 | HARRISON | YYC→YOW | Comp processing outage | Error handling |

---

## Notes

1. All PNRs have flight date **2026-06-25**
2. All passengers use OTP email: **chathuranga.viraj.qa@gmail.com**
3. Multi-pax PNRs: ZFD015 (3 pax), ZFD029 (adult+infant), ZFD132-134 (2 pax each)
4. Disruption/delay data (DDS) needs to be seeded separately for eligibility testing
