"""
Wave-3 AI Productivity Beneficiary Universe.

Each entry: (ticker, sector_bucket, how_ai_helps, primary_metric_tag).

primary_metric_tag drives which screen the company is most exposed to:
  LABOR_PCT      - labor cost as % of sales (Goldman GSXUPROD #1 metric)
  REV_PER_EMP    - revenue / full-time employees (low = labor intensive)
  SGA_PCT        - SG&A / revenue (high = automatable admin overhead)
  CS_INTENSITY   - customer-service / contact-center exposure
  CLAIMS_INTENS  - insurance claims/adjustment exposure
  BACKOFFICE     - back-office processing (payments/payroll/HR/accounting)
  KNOW_WORKER    - knowledge worker (consulting/legal/research) exposure
  BILL_HOURS     - billable-hours business model
  BPO            - outsourced business-process exposure
"""

UNIVERSE = [
    # ===== IT Services & Consulting (BILL_HOURS / KNOW_WORKER) =====
    ("CTSH",  "IT Services",        "76% of revenue is labor; agentic coding compresses billable hours and SOW delivery time", "LABOR_PCT"),
    ("EPAM",  "IT Services",        "53% labor; offshore-heavy delivery model directly substituted by code-gen agents",      "LABOR_PCT"),
    ("ACN",   "IT Services",        "Knowledge-worker pyramid; AI replaces first-year analyst/associate work, expands pricing", "BILL_HOURS"),
    ("INFY",  "IT Services",        "Indian-IT model — application maintenance + BPO directly automatable",                  "LABOR_PCT"),
    ("WIT",   "IT Services",        "Same offshore IT model as INFY; high billable-hour share",                              "LABOR_PCT"),
    ("G",     "BPO",                "Transactional F&A BPO — invoice processing, AR/AP automation",                          "BPO"),
    ("EXLS",  "BPO",                "Analytics + claims BPO; insurance back-office heavy",                                   "BPO"),
    ("DXC",   "IT Services",        "Legacy IT outsourcing; ticket triage and L1/L2 support fully agent-able",               "LABOR_PCT"),
    ("KD",    "IT Services",        "IBM infra-services spinoff; managed infra ops automatable",                             "LABOR_PCT"),
    ("CACI",  "Gov IT Services",    "Government IT services; same SOW pyramid",                                              "BILL_HOURS"),
    ("LDOS",  "Gov IT Services",    "Defense + civil IT services",                                                           "BILL_HOURS"),
    ("BAH",   "Gov Consulting",     "Government consulting; knowledge-worker model",                                         "KNOW_WORKER"),
    ("GLOB",  "IT Services",        "Digital engineering services; code-gen displaces a chunk of dev hours",                 "BILL_HOURS"),
    ("IT",    "Research/Advisory",  "Research & advisory; LLMs replicate analyst report writing",                            "KNOW_WORKER"),
    ("FCN",   "Consulting",         "FTI consulting — expert witness + restructuring; document review automatable",          "KNOW_WORKER"),
    ("HURN",  "Consulting",         "Healthcare/education consulting",                                                       "KNOW_WORKER"),

    # ===== Staffing & HR Services (LABOR_PCT) =====
    ("RHI",   "Staffing",           "79% labor; matching + screening = textbook agentic workflow",                           "LABOR_PCT"),
    ("MAN",   "Staffing",           "Global staffing; high SG&A on branch-network labor",                                    "LABOR_PCT"),
    ("ASGN",  "Staffing",           "IT/professional staffing",                                                              "LABOR_PCT"),
    ("KFY",   "Executive Search",   "Search + consulting hybrid; AI screens candidates",                                     "KNOW_WORKER"),
    ("HSII",  "Executive Search",   "Pure exec search — sourcing agents replace researchers",                                "KNOW_WORKER"),
    ("KFRC",  "Staffing",           "Tech-focused staffing",                                                                 "LABOR_PCT"),

    # ===== Payroll & HR Tech (BACKOFFICE) =====
    ("PAYX",  "Payroll/HR",         "Payroll service-bureau labor; AI compresses CS + onboarding",                           "BACKOFFICE"),
    ("ADP",   "Payroll/HR",         "Same model at larger scale; CS heavy",                                                  "BACKOFFICE"),
    ("PCTY",  "HR Tech",            "Mid-market HR — implementation & support staff",                                       "BACKOFFICE"),
    ("PAYC",  "HR Tech",            "Same",                                                                                  "BACKOFFICE"),

    # ===== Tax / Accounting / Doc-Heavy Fin Services =====
    ("HRB",   "Tax Services",       "46% labor / 97th %ile (Goldman); tax-prep workflow fully agent-able",                   "LABOR_PCT"),
    ("INTU",  "Fintech Software",   "Building the AI agent; TurboTax/QBO margin expansion",                                  "BACKOFFICE"),
    ("JKHY",  "Bank Tech",          "Community-bank back-office software",                                                   "BACKOFFICE"),
    ("FIS",   "Bank Tech",          "Same — payments + bank ops automation",                                                 "BACKOFFICE"),
    ("FI",    "Bank Tech",          "Fiserv — large payment + bank back-office",                                             "BACKOFFICE"),
    ("BR",    "Bank Tech",          "Broadridge — proxy/regulatory ops",                                                     "BACKOFFICE"),

    # ===== Healthcare Admin / CRO =====
    ("IQV",   "CRO",                "45% labor (Goldman); clinical-trial data mgmt + monitoring",                            "LABOR_PCT"),
    ("CRL",   "CRO",                "Preclinical CRO — lab labor",                                                           "LABOR_PCT"),
    ("ICLR",  "CRO",                "Late-stage CRO",                                                                        "LABOR_PCT"),
    ("MEDP",  "CRO",                "Mid-cap CRO",                                                                           "LABOR_PCT"),
    ("EVH",   "Health Tech",        "Value-based care admin — claims + analytics",                                           "CLAIMS_INTENS"),
    ("MDRX",  "Health IT",          "EHR/admin software; AI scribe + agentic billing",                                       "BACKOFFICE"),
    ("HQY",   "Benefits Admin",     "HSA + COBRA admin — back-office processing",                                            "BACKOFFICE"),
    ("PINC",  "Healthcare GPO",     "Healthcare GPO admin",                                                                  "BACKOFFICE"),
    ("OMI",   "Healthcare Distrib", "Distribution + back office",                                                            "BACKOFFICE"),

    # ===== Insurance =====
    ("MMC",   "Insurance Broker",   "Brokerage admin + advisory; agentic policy mgmt",                                       "BACKOFFICE"),
    ("AON",   "Insurance Broker",   "Same",                                                                                  "BACKOFFICE"),
    ("WTW",   "Insurance Broker",   "Same + HR consulting",                                                                  "KNOW_WORKER"),
    ("AJG",   "Insurance Broker",   "Mid-market broker",                                                                     "BACKOFFICE"),
    ("BRO",   "Insurance Broker",   "Brown & Brown",                                                                         "BACKOFFICE"),
    ("EHTH",  "Insurance Marketplace","High agent labor; AI displaces ACA navigators",                                       "CS_INTENSITY"),
    ("GOCO",  "Insurance Marketplace","Same as EHTH",                                                                        "CS_INTENSITY"),
    ("TRV",   "P&C Insurance",      "Claims processing — agentic AI cuts loss adjustment expense ratio",                     "CLAIMS_INTENS"),
    ("CINF",  "P&C Insurance",      "Same — mid-cap P&C",                                                                    "CLAIMS_INTENS"),
    ("ALL",   "P&C Insurance",      "Personal lines claims",                                                                 "CLAIMS_INTENS"),
    ("HIG",   "P&C Insurance",      "Commercial + group benefits claims",                                                    "CLAIMS_INTENS"),
    ("CB",    "P&C Insurance",      "Specialty commercial; underwriting AI",                                                 "CLAIMS_INTENS"),
    ("PRU",   "Life Insurance",     "Annuity admin + underwriting heavy",                                                    "CLAIMS_INTENS"),
    ("MET",   "Life Insurance",     "Same",                                                                                  "CLAIMS_INTENS"),
    ("LNC",   "Life Insurance",     "Same — smaller",                                                                        "CLAIMS_INTENS"),

    # ===== Legal / Information / Compliance =====
    ("TRI",   "Legal/Info",         "Westlaw + CoCounsel agent — both sides of the trade",                                   "KNOW_WORKER"),
    ("RELX",  "Legal/Info",         "LexisNexis — same",                                                                     "KNOW_WORKER"),
    ("WLY",   "Publishing",         "Academic content; AI summarization",                                                    "KNOW_WORKER"),
    ("WK",    "Compliance SW",      "Workiva — disclosure mgmt automation",                                                  "BACKOFFICE"),

    # ===== Customer Support / Contact Center / BPO =====
    ("TTEC",  "CX BPO",             "Most-exposed name on Earth — direct voice-agent substitution",                          "CS_INTENSITY"),
    ("CNDT",  "CX BPO",             "Conduent — same",                                                                       "CS_INTENSITY"),
    ("CNXC",  "CX BPO",             "Concentrix — $9B revenue, ~440K employees — extreme labor leverage",                    "CS_INTENSITY"),
    ("IBEX",  "CX BPO",             "Small-cap BPO",                                                                         "CS_INTENSITY"),
    ("NICE",  "CCaaS Software",     "Contact-center software building the AI layer (beneficiary side)",                      "BACKOFFICE"),
    ("FIVN",  "CCaaS Software",     "Same — direct AI agent monetization",                                                   "BACKOFFICE"),
    ("ZM",    "Comms/CCaaS",        "Zoom AI Companion + contact center pivot",                                              "BACKOFFICE"),
    ("RNG",   "CCaaS Software",     "RingCentral — AI-native call center push",                                              "BACKOFFICE"),

    # ===== Regional & Mid-Cap Banks =====
    ("TFC",   "Regional Bank",      "Branch + back-office labor; AI cuts opex bps",                                          "BACKOFFICE"),
    ("USB",   "Regional Bank",      "Same — super-regional",                                                                 "BACKOFFICE"),
    ("PNC",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("RF",    "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("CFG",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("KEY",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("FITB",  "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("MTB",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("HBAN",  "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("ZION",  "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("CMA",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),
    ("WAL",   "Regional Bank",      "Same",                                                                                  "BACKOFFICE"),

    # ===== Money-Center Banks =====
    ("JPM",   "Money Center Bank",  "Internal AI org — Dimon cited '10% ops cut'",                                           "BACKOFFICE"),
    ("BAC",   "Money Center Bank",  "Targeting 200+bps operating leverage via AI",                                           "BACKOFFICE"),
    ("WFC",   "Money Center Bank",  "Branch + back office",                                                                  "BACKOFFICE"),
    ("C",     "Money Center Bank",  "Restructuring + AI ops modernization",                                                  "BACKOFFICE"),

    # ===== Media / Advertising =====
    ("OMC",   "Ad Agency",          "Knowledge-worker model; AI creative tooling cuts headcount",                            "KNOW_WORKER"),
    ("IPG",   "Ad Agency",          "Same; consolidating w/ OMC",                                                            "KNOW_WORKER"),
    ("NYT",   "Publisher",          "Translation + editorial automation",                                                    "KNOW_WORKER"),
    ("GCI",   "Publisher",          "Gannett — newsroom labor",                                                              "KNOW_WORKER"),

    # ===== Logistics & Field Services =====
    ("CHRW",  "Freight Broker",     "Brokerage labor (load matching + quoting) — direct AI substitution",                    "CS_INTENSITY"),
    ("EXPD",  "Freight Forwarder",  "Door-to-door coordination — call center heavy",                                         "CS_INTENSITY"),
    ("HUBG",  "Freight Broker",     "Same",                                                                                  "CS_INTENSITY"),
    ("XPO",   "LTL/Logistics",      "Dispatch + appointment scheduling",                                                     "BACKOFFICE"),
    ("GXO",   "Logistics",          "Warehouse ops + admin",                                                                 "BACKOFFICE"),
    ("ROL",   "Pest Control",       "Dispatch + scheduling labor",                                                           "BACKOFFICE"),
    ("SCI",   "Funeral Services",   "Service Corp — admin back office",                                                      "BACKOFFICE"),
    ("RBA",   "Auctions",           "RB Global — auction admin",                                                             "BACKOFFICE"),

    # ===== Real Estate Services =====
    ("CBRE",  "RE Services",        "Brokerage labor + property mgmt admin",                                                 "KNOW_WORKER"),
    ("JLL",   "RE Services",        "Same",                                                                                  "KNOW_WORKER"),
    ("CWK",   "RE Services",        "Cushman & Wakefield",                                                                   "KNOW_WORKER"),
    ("NMRK",  "RE Services",        "Newmark",                                                                               "KNOW_WORKER"),
    ("RDFN",  "Real Estate",        "Redfin — agent + ops labor",                                                            "CS_INTENSITY"),
    ("Z",     "Real Estate",        "Zillow — listings + leads ops",                                                         "CS_INTENSITY"),
    ("COMP",  "Real Estate",        "Compass — same",                                                                        "CS_INTENSITY"),

    # ===== Government Services Contractors =====
    ("MAXR",  "Gov BPO",            "MAXIMUS — government BPO (Medicare/Medicaid call center)",                              "CS_INTENSITY"),
    ("ICFI",  "Gov Consulting",     "Federal IT/consulting",                                                                 "KNOW_WORKER"),
    ("TYL",   "Gov Software",       "Building the AI tools, but heavy implementation staff",                                 "BACKOFFICE"),

    # ===== Education / Training Services =====
    ("CHGG",  "Online Learning",    "Direct AI substitution risk — but pivoting to AI tutor",                                "KNOW_WORKER"),
    ("STRA",  "Education Services", "Strategic Education — admin + course-development labor",                                "KNOW_WORKER"),
    ("LRN",   "K-12 Education",     "Stride — virtual instruction labor",                                                    "KNOW_WORKER"),
    ("LAUR",  "Higher Ed",          "Laureate — back-office admin",                                                          "BACKOFFICE"),
    ("COUR",  "Online Learning",    "Coursera — content + grading automation",                                               "KNOW_WORKER"),

    # ===== Asset/Wealth Management =====
    ("BLK",   "Asset Mgmt",         "Aladdin + research analyst leverage",                                                   "KNOW_WORKER"),
    ("TROW",  "Asset Mgmt",         "Research-analyst pyramid",                                                              "KNOW_WORKER"),
    ("BEN",   "Asset Mgmt",         "Same",                                                                                  "KNOW_WORKER"),
    ("AMG",   "Asset Mgmt",         "Same",                                                                                  "KNOW_WORKER"),
    ("LPLA",  "Wealth Mgmt",        "Advisor support back office",                                                           "BACKOFFICE"),
    ("RJF",   "Wealth Mgmt",        "Raymond James — same",                                                                  "BACKOFFICE"),
    ("AMP",   "Wealth Mgmt",        "Ameriprise — same",                                                                     "BACKOFFICE"),

    # ===== Specialty Back-Office / Doc Processing =====
    ("PBI",   "Doc Processing",     "Pitney Bowes — mail/doc workflow legacy",                                               "BACKOFFICE"),
    ("ACIW",  "Payments Software",  "ACI — payments middleware ops",                                                         "BACKOFFICE"),
    ("EVRI",  "Gaming Tech",        "Field-service + back office",                                                           "BACKOFFICE"),
    ("DLX",   "Print/Marketing",    "Deluxe — checks + marketing services",                                                  "BACKOFFICE"),

    # ===== Marketing / Mid-Office Software =====
    ("WDAY",  "HCM Software",       "Building AI but heavy services revenue",                                                "BACKOFFICE"),
    ("CRM",   "Enterprise Software","Agentforce — building the agent, services cuts",                                        "BACKOFFICE"),
    ("NOW",   "Enterprise Software","ServiceNow — IT/ops AI agents",                                                         "BACKOFFICE"),
    ("HUBS",  "Marketing Software", "HubSpot — Breeze AI agents",                                                            "BACKOFFICE"),
    ("DOCU",  "Doc Software",       "DocuSign Maestro — agreement automation",                                               "BACKOFFICE"),

    # ===== Healthcare Payers (admin-heavy) =====
    ("UNH",   "Health Insurance",   "Optum admin + prior auth automation",                                                   "CLAIMS_INTENS"),
    ("ELV",   "Health Insurance",   "Same — Elevance",                                                                       "CLAIMS_INTENS"),
    ("HUM",   "Health Insurance",   "Same — Humana",                                                                         "CLAIMS_INTENS"),
    ("CNC",   "Health Insurance",   "Medicaid claims",                                                                       "CLAIMS_INTENS"),
    ("MOH",   "Health Insurance",   "Medicaid managed care",                                                                 "CLAIMS_INTENS"),
    ("CI",    "Health Insurance",   "Cigna + Evernorth (PBM)",                                                               "CLAIMS_INTENS"),

    # ===== Retail Banks & Specialty Lenders =====
    ("SCHW",  "Brokerage",          "Self-service brokerage; AI compresses CS",                                              "CS_INTENSITY"),
    ("IBKR",  "Brokerage",          "Already efficient — comparison anchor",                                                 "CS_INTENSITY"),
    ("HOOD",  "Brokerage",          "Camillo top pick; high rev/employee benchmark",                                         "CS_INTENSITY"),
    ("COF",   "Cards/Bank",         "Servicing + collections",                                                               "BACKOFFICE"),
    ("DFS",   "Cards",              "Same",                                                                                  "BACKOFFICE"),
    ("SYF",   "Cards",              "Synchrony — collections heavy",                                                         "BACKOFFICE"),
    ("ALLY",  "Auto Finance",       "Servicing back office",                                                                 "BACKOFFICE"),
]
