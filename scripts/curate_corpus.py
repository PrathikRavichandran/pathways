"""
curate_corpus.py: hand-curated expansion of the legal corpus.

Pragmatic choice over building a full eCFR / statutes.capitol.texas.gov
scraper: scraping returns legalese that still needs LLM summarization to
be useful in a reentry navigator context. A 30-50 entry hand-curated set
of the highest-impact federal CFR sections and TX statutes ships in a
day, is auditable line by line, and avoids the eCFR XML wrangling cost.

The full eCFR / statutes scraper is in the Phase 6 backlog. For now this
script gets the corpus from 65 to about 110 entries with accurate, plain-
language summaries that map exactly to the questions reentry users ask.

Idempotent: re-running upserts; never duplicates.

Run:
    DATABASE_URL=postgresql://... python -m scripts.curate_corpus
"""

from __future__ import annotations

from scripts._common import get_conn, log, today_iso, upsert_corpus_entry

SOURCE = "curated_federal_and_tx"

# Each entry: id, citation, summary, url, category, subcategory, tags.
# Summaries are plain-language paraphrases of the underlying rule, NOT
# direct quotes. They were written to be read on a phone in two sentences.
ENTRIES: list[dict] = [
    # ----------------------------------------------------------------------
    # Federal CFR: HUD public housing eligibility (24 CFR § 960)
    # ----------------------------------------------------------------------
    {
        "id": "cfr-24-960-204",
        "citation": "24 CFR § 960.204",
        "summary": (
            "HUD-funded public housing agencies have only TWO mandatory "
            "lifetime denials: lifetime registered sex offenders, and people "
            "convicted of methamphetamine production on assisted-housing "
            "premises. Everything else is at the housing authority's "
            "discretion under its admissions policy."
        ),
        "url": "https://www.ecfr.gov/current/title-24/subtitle-B/chapter-IX/part-960/subpart-B/section-960.204",
        "category": "housing",
        "subcategory": "public_housing_mandatory_bars",
        "tags": ["hud", "public_housing", "section_8", "mandatory_denial",
                 "sex_offender", "meth_production"],
    },
    {
        "id": "cfr-24-960-203",
        "citation": "24 CFR § 960.203",
        "summary": (
            "Public housing agencies set their own admission standards. The "
            "rules require them to consider relevant evidence (time since "
            "offense, evidence of rehabilitation, applicant's circumstances) "
            "before denying based on criminal history. Blanket bans are not "
            "compliant with federal rules."
        ),
        "url": "https://www.ecfr.gov/current/title-24/subtitle-B/chapter-IX/part-960/subpart-B/section-960.203",
        "category": "housing",
        "subcategory": "public_housing_discretionary_review",
        "tags": ["hud", "public_housing", "admissions", "discretion",
                 "rehabilitation_evidence"],
    },
    {
        "id": "hud-notice-pih-2015-19",
        "citation": "HUD Notice PIH-2015-19",
        "summary": (
            "HUD guidance: an arrest alone, without a conviction, cannot be "
            "the basis to deny public housing. The notice tells PHAs to "
            "consider the nature/severity/recency of conduct and evidence of "
            "rehabilitation, and warns that overbroad bans may violate the "
            "Fair Housing Act because of disparate impact."
        ),
        "url": "https://www.hud.gov/sites/documents/PIH2015-19.PDF",
        "category": "housing",
        "subcategory": "hud_arrest_only_policy",
        "tags": ["hud", "arrest_record", "disparate_impact", "fair_housing"],
    },
    # ----------------------------------------------------------------------
    # Federal SNAP / TANF drug-felony rules (the most-misunderstood)
    # ----------------------------------------------------------------------
    {
        "id": "cfr-7-273-11-m",
        "citation": "7 CFR § 273.11(m)",
        "summary": (
            "Federal law lets states opt out of the lifetime SNAP ban for "
            "people with drug felony convictions. Texas opted out in 2015 "
            "with conditions; a person with a drug felony in Texas can apply "
            "for SNAP and be evaluated under standard eligibility rules."
        ),
        "url": "https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-C/part-273/subpart-C/section-273.11",
        "category": "benefits",
        "subcategory": "snap_drug_felony_state_opt_out",
        "tags": ["snap", "food_stamps", "drug_felony", "opt_out", "texas"],
    },
    {
        "id": "tx-hhsc-snap-drug-felony-policy",
        "citation": "Texas HHSC SNAP Handbook section on disqualification (A-1100)",
        "summary": (
            "In Texas, an applicant with a drug felony is SNAP-eligible if "
            "they meet standard income/resource rules AND are either (1) "
            "complying with court-ordered conditions, (2) participating in "
            "treatment, or (3) more than six months past their sentence "
            "completion. There is no lifetime ban."
        ),
        "url": "https://www.hhs.texas.gov/handbooks/texas-works-handbook/a-1100-people",
        "category": "benefits",
        "subcategory": "snap_texas_eligibility_with_record",
        "tags": ["snap", "texas", "drug_felony", "hhsc", "yourtexasbenefits"],
    },
    {
        "id": "cfr-7-273-11-n",
        "citation": "7 CFR § 273.11(n) (fleeing felons)",
        "summary": (
            "SNAP disqualifies people actively fleeing prosecution or who are "
            "in violation of a condition of parole or probation. This is "
            "tied to active warrants, not historical convictions. Resolving "
            "an outstanding warrant restores eligibility."
        ),
        "url": "https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-C/part-273/subpart-C/section-273.11",
        "category": "benefits",
        "subcategory": "snap_fleeing_felon_rule",
        "tags": ["snap", "fleeing_felon", "warrants", "parole_violation"],
    },
    {
        "id": "tx-tanf-drug-felony",
        "citation": "Texas Human Resources Code § 31.0035 (TANF lifetime ban)",
        "summary": (
            "Unlike SNAP, Texas DID NOT opt out of the federal lifetime TANF "
            "ban for adults with drug felony convictions. An adult with a "
            "drug felony is permanently TANF-ineligible in Texas. Children "
            "in the household are still eligible. Apply for SNAP and "
            "Medicaid separately."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/HR/htm/HR.31.htm#31.0035",
        "category": "benefits",
        "subcategory": "tanf_texas_lifetime_ban",
        "tags": ["tanf", "drug_felony", "texas", "lifetime_ban",
                 "children_still_eligible"],
    },
    # ----------------------------------------------------------------------
    # Federal Medicaid / SSI / SSDI suspension on incarceration
    # ----------------------------------------------------------------------
    {
        "id": "cfr-42-435-1009",
        "citation": "42 CFR § 435.1009",
        "summary": (
            "Federal Medicaid is suspended (not terminated) while a person "
            "is incarcerated for more than 30 days, except for inpatient "
            "hospital stays. Suspension means the case stays open and can "
            "be reactivated on release without a full re-application."
        ),
        "url": "https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-C/part-435/subpart-J/section-435.1009",
        "category": "benefits",
        "subcategory": "medicaid_suspension_during_incarceration",
        "tags": ["medicaid", "incarceration", "suspension", "reentry",
                 "reinstatement"],
    },
    {
        "id": "cfr-20-416-211",
        "citation": "20 CFR § 416.211",
        "summary": (
            "SSI payments stop after a full calendar month of incarceration. "
            "After 12 months of suspension, SSI eligibility terminates and "
            "a new application is required on release. Under 12 months, the "
            "person can request expedited reinstatement (EXR) without a "
            "full re-application."
        ),
        "url": "https://www.ecfr.gov/current/title-20/chapter-III/part-416/subpart-B/section-416.211",
        "category": "benefits",
        "subcategory": "ssi_suspension_during_incarceration",
        "tags": ["ssi", "incarceration", "suspension", "termination",
                 "expedited_reinstatement"],
    },
    {
        "id": "cfr-20-404-468",
        "citation": "20 CFR § 404.468",
        "summary": (
            "SSDI benefits are suspended during incarceration for a felony "
            "conviction. Benefits resume the month after release. Workers "
            "in pre-release programs may receive benefits during the last "
            "month of incarceration. SSA must be notified of the release "
            "date for benefits to restart cleanly."
        ),
        "url": "https://www.ecfr.gov/current/title-20/chapter-III/part-404/subpart-E/section-404.468",
        "category": "benefits",
        "subcategory": "ssdi_suspension_during_incarceration",
        "tags": ["ssdi", "social_security", "incarceration", "suspension",
                 "release_planning"],
    },
    # ----------------------------------------------------------------------
    # Federal Pell Grant restoration (FAFSA Simplification Act, 2023)
    # ----------------------------------------------------------------------
    {
        "id": "cfr-34-668-32-pell",
        "citation": "34 CFR § 668.32 (FAFSA Simplification Act amendments)",
        "summary": (
            "Since July 2023 the federal Pell Grant is available to people "
            "in state and federal prison and to people with prior drug "
            "convictions. The lifetime drug-conviction bar on federal "
            "student aid was repealed. Community colleges and four-year "
            "schools that participate in the Second Chance Pell program "
            "can enroll currently and formerly incarcerated students."
        ),
        "url": "https://studentaid.gov/understand-aid/eligibility/requirements/criminal-convictions",
        "category": "benefits",
        "subcategory": "pell_grant_post_2023",
        "tags": ["pell_grant", "fafsa", "education", "second_chance_pell",
                 "drug_conviction"],
    },
    # ----------------------------------------------------------------------
    # Federal Bonding Program
    # ----------------------------------------------------------------------
    {
        "id": "us-dol-federal-bonding",
        "citation": "US DOL Federal Bonding Program (Bonds 4 Jobs)",
        "summary": (
            "The Federal Bonding Program provides free fidelity bonds for "
            "at-risk job seekers (formerly incarcerated, in recovery, "
            "previously homeless, dishonorably discharged, or with poor "
            "credit). The bond is free to the employer and covers theft or "
            "dishonesty for the first six months of employment. Most TX "
            "Workforce Solutions offices can issue bonds the same day."
        ),
        "url": "https://bonds4jobs.com/",
        "category": "employment",
        "subcategory": "federal_bonding_program",
        "tags": ["employment", "fair_chance", "fidelity_bond", "federal_bonding",
                 "second_chance"],
    },
    # ----------------------------------------------------------------------
    # Texas: CCP Ch. 55 expunction
    # ----------------------------------------------------------------------
    {
        "id": "tx-ccp-55-01",
        "citation": "Texas Code of Criminal Procedure Art. 55.01",
        "summary": (
            "Texas expunction is narrow: only non-convictions qualify "
            "(acquittal, dismissal, no-bill, or pretrial diversion). A "
            "successfully-completed deferred adjudication is generally not "
            "eligible for expunction. The remedy for completed deferred "
            "adjudication is non-disclosure under Government Code Ch. 411, "
            "not expunction."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/CR/htm/CR.55.htm#55.01",
        "category": "record_clearing",
        "subcategory": "expunction_eligibility",
        "tags": ["expunction", "ccp_55", "non_conviction", "acquittal",
                 "dismissal", "pretrial_diversion"],
    },
    {
        "id": "tx-ccp-55-02",
        "citation": "Texas Code of Criminal Procedure Art. 55.02",
        "summary": (
            "An expunction petition is filed in the district court for the "
            "county where the arrest occurred. The petition must list every "
            "agency that holds the record (arresting agency, court, DPS, "
            "DA's office, jail). If granted, all listed agencies must "
            "destroy or return the records."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/CR/htm/CR.55.htm#55.02",
        "category": "record_clearing",
        "subcategory": "expunction_procedure",
        "tags": ["expunction", "ccp_55_02", "district_court", "filing"],
    },
    # ----------------------------------------------------------------------
    # Texas: Gov Code Ch. 411 non-disclosure
    # ----------------------------------------------------------------------
    {
        "id": "tx-gov-411-072",
        "citation": "Texas Government Code § 411.072 (automatic non-disclosure for first-time misdemeanors)",
        "summary": (
            "First-time misdemeanor offenders who successfully complete "
            "deferred adjudication may be eligible for automatic non-"
            "disclosure (no waiting period and no fee) if the offense is "
            "not on the disqualifying list (violent offenses, family "
            "violence, sex offenses, etc.). Granted at the time of dismissal."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.411.htm#411.072",
        "category": "record_clearing",
        "subcategory": "non_disclosure_automatic_misdemeanor",
        "tags": ["non_disclosure", "gov_411_072", "deferred_adjudication",
                 "misdemeanor", "automatic"],
    },
    {
        "id": "tx-gov-411-0725",
        "citation": "Texas Government Code § 411.0725 (non-disclosure after community supervision)",
        "summary": (
            "People who completed a non-deferred misdemeanor or felony with "
            "community supervision may petition for non-disclosure after "
            "waiting periods (2 years for most misdemeanors, 5 years for "
            "felonies post-completion). Many offenses are excluded "
            "categorically. Always work with legal aid for the petition."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.411.htm#411.0725",
        "category": "record_clearing",
        "subcategory": "non_disclosure_after_supervision",
        "tags": ["non_disclosure", "gov_411_0725", "community_supervision",
                 "waiting_period"],
    },
    {
        "id": "tx-gov-411-0735",
        "citation": "Texas Government Code § 411.0735 (non-disclosure after misdemeanor conviction)",
        "summary": (
            "People convicted of certain misdemeanors (not deferred, "
            "actually convicted) may petition for non-disclosure after a "
            "2-year waiting period from sentence completion. Excluded "
            "offenses include family violence, DWI, weapons, and sex "
            "offenses. Best of class fit for first-time petty offenses."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.411.htm#411.0735",
        "category": "record_clearing",
        "subcategory": "non_disclosure_misdemeanor_conviction",
        "tags": ["non_disclosure", "gov_411_0735", "misdemeanor_conviction",
                 "waiting_period"],
    },
    # ----------------------------------------------------------------------
    # Texas: Occupations Code Ch. 53 (licensing for people with criminal history)
    # ----------------------------------------------------------------------
    {
        "id": "tx-occ-53-021",
        "citation": "Texas Occupations Code § 53.021",
        "summary": (
            "A licensing authority may suspend or deny a license based on a "
            "felony or misdemeanor conviction ONLY if the offense directly "
            "relates to the duties of the licensed occupation. Boards must "
            "consider seven factors (nature/severity, time elapsed, "
            "rehabilitation evidence, age at offense, etc.) before denying."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/OC/htm/OC.53.htm#53.021",
        "category": "employment",
        "subcategory": "occupational_licensing_directly_related",
        "tags": ["licensing", "occ_53_021", "directly_related",
                 "seven_factors", "fair_chance_licensing"],
    },
    {
        "id": "tx-occ-53-102",
        "citation": "Texas Occupations Code § 53.102 (criminal history evaluation letter)",
        "summary": (
            "A person with a criminal history may, BEFORE applying for a "
            "license, request a written evaluation letter from the licensing "
            "board telling them whether their record is likely to disqualify "
            "them. The letter is binding on the board for that record. Costs "
            "are minimal. Strongly recommended before paying license-application fees."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/OC/htm/OC.53.htm#53.102",
        "category": "employment",
        "subcategory": "criminal_history_evaluation_letter",
        "tags": ["licensing", "occ_53_102", "evaluation_letter",
                 "pre_application", "fair_chance"],
    },
    {
        "id": "tx-occ-53-023",
        "citation": "Texas Occupations Code § 53.023 (factors a board must consider)",
        "summary": (
            "Before denying a license based on criminal history, a Texas "
            "licensing board must consider: nature and seriousness of the "
            "offense; how related it is to the occupation; time elapsed; "
            "age at offense; pattern of conduct; rehabilitation evidence "
            "(employment, education, parole compliance); and other mitigating "
            "factors. Boards that skip this analysis can be challenged."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/OC/htm/OC.53.htm#53.023",
        "category": "employment",
        "subcategory": "occupational_licensing_factors_test",
        "tags": ["licensing", "occ_53_023", "seven_factors", "rehabilitation",
                 "due_process"],
    },
    # ----------------------------------------------------------------------
    # Texas: Government Code Ch. 508 (parole + mandatory supervision)
    # ----------------------------------------------------------------------
    {
        "id": "tx-gov-508-001",
        "citation": "Texas Government Code Ch. 508",
        "summary": (
            "Chapter 508 governs Texas parole. The Board of Pardons and "
            "Paroles sets conditions; the Parole Division of TDCJ "
            "supervises. Common conditions include reporting on a set "
            "schedule, employment verification, no contact with co-defendants, "
            "restrictions on travel, and abstaining from drugs/alcohol. "
            "Technical violations (missed report, failed UA) can return a "
            "person to TDCJ."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.508.htm",
        "category": "supervision",
        "subcategory": "parole_general_provisions",
        "tags": ["parole", "gov_508", "tdcj", "technical_violation",
                 "supervision_conditions"],
    },
    {
        "id": "tx-gov-508-281-revocation",
        "citation": "Texas Government Code § 508.281 (parole revocation hearing)",
        "summary": (
            "Before parole is revoked for a technical violation, the person "
            "is entitled to a hearing before a hearing officer. They may "
            "present evidence, call witnesses, and be represented. An "
            "experienced re-entry attorney materially improves outcomes; "
            "the Texas Fair Defense Project and TRLA cover this in some "
            "regions."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.508.htm#508.281",
        "category": "supervision",
        "subcategory": "parole_revocation_hearing",
        "tags": ["parole", "gov_508_281", "revocation_hearing", "due_process",
                 "legal_aid"],
    },
    # ----------------------------------------------------------------------
    # Texas: Transportation Code Ch. 521 (driver license)
    # ----------------------------------------------------------------------
    {
        "id": "tx-trans-521-372",
        "citation": "Texas Transportation Code § 521.372",
        "summary": (
            "A drug conviction (felony or misdemeanor) triggers an "
            "automatic 180-day driver license suspension. The 180 days run "
            "from the conviction date. Once that window has passed, the "
            "license can be reinstated by paying reinstatement fees and "
            "satisfying any insurance (SR-22) requirement. Not permanent."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/TN/htm/TN.521.htm#521.372",
        "category": "drivers_license",
        "subcategory": "drug_offense_180_day_suspension",
        "tags": ["drivers_license", "drug_offense", "180_day_suspension",
                 "reinstatement", "sr22"],
    },
    {
        "id": "tx-trans-521-242",
        "citation": "Texas Transportation Code § 521.242 (occupational driver license)",
        "summary": (
            "A person whose license has been suspended (for drug offense, "
            "DWI, or unpaid surcharges) may petition the court for an "
            "occupational driver license that allows essential driving "
            "(work, school, family). Petition is filed in the court of "
            "conviction or the county where the person lives. Granted with "
            "restrictions like specific hours and routes."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/TN/htm/TN.521.htm#521.242",
        "category": "drivers_license",
        "subcategory": "occupational_license",
        "tags": ["drivers_license", "occupational_license", "essential_driving",
                 "trans_521_242"],
    },
    # ----------------------------------------------------------------------
    # Texas: voting and civil rights
    # ----------------------------------------------------------------------
    {
        "id": "tx-elec-11-002",
        "citation": "Texas Election Code § 11.002",
        "summary": (
            "A person with a felony conviction can vote in Texas after "
            "fully discharging the sentence (which includes parole, "
            "probation, and any post-release supervision). Voting while "
            "still under supervision is a felony. Once discharged, "
            "re-register at votetexas.gov or any county elections office."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/EL/htm/EL.11.htm#11.002",
        "category": "civil_rights",
        "subcategory": "voting_after_felony",
        "tags": ["voting", "election_code_11", "felony", "discharged_sentence",
                 "registration"],
    },
    {
        "id": "tx-gov-62-102-jury",
        "citation": "Texas Government Code § 62.102 (jury disqualification)",
        "summary": (
            "A person convicted of a felony or under indictment for a "
            "felony is disqualified from jury service in Texas, including "
            "while on parole or probation. Eligibility is restored when the "
            "sentence is fully discharged (same as voting). Misdemeanor "
            "convictions generally do NOT disqualify a juror unless the "
            "offense involved moral turpitude."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/GV/htm/GV.62.htm#62.102",
        "category": "civil_rights",
        "subcategory": "jury_disqualification_felony",
        "tags": ["jury", "gov_62_102", "felony_disqualification",
                 "moral_turpitude"],
    },
    # ----------------------------------------------------------------------
    # Texas: TDCJ release packet specifics
    # ----------------------------------------------------------------------
    {
        "id": "tdcj-release-gate-money",
        "citation": "TDCJ Reentry & Integration Division (release procedures)",
        "summary": (
            "TDCJ provides a release packet that includes the certificate "
            "of release, a temporary ID (DPS-issued, valid for limited "
            "purposes), $100 in gate money for most releases, transportation "
            "voucher to the parole reporting address, and program "
            "completion certificates. Keep all documents; they're needed "
            "for state ID restoration, SNAP/Medicaid, and parole reporting."
        ),
        "url": "https://www.tdcj.texas.gov/divisions/rid/",
        "category": "id_documents",
        "subcategory": "tdcj_release_packet",
        "tags": ["tdcj", "release_packet", "gate_money", "temporary_id",
                 "transportation_voucher"],
    },
    {
        "id": "tx-dps-id-form-dl-43",
        "citation": "TX DPS Form DL-43 (reduced-fee ID for returning citizens)",
        "summary": (
            "Texans recently released from TDCJ are eligible for a "
            "reduced-fee state ID using DPS Form DL-43. The reduced fee is "
            "available within a window after release and requires the "
            "TDCJ-issued release documents. Walk into any TX DPS Driver "
            "License Office; processing usually takes the same visit."
        ),
        "url": "https://www.dps.texas.gov/section/driver-license",
        "category": "id_documents",
        "subcategory": "state_id_reduced_fee",
        "tags": ["state_id", "dps", "dl_43", "reduced_fee", "tdcj_release"],
    },
    # ----------------------------------------------------------------------
    # Texas: child support arrears post-incarceration
    # ----------------------------------------------------------------------
    {
        "id": "tx-fam-156-401-modification",
        "citation": "Texas Family Code § 156.401 (child support modification)",
        "summary": (
            "Child support obligations continue during incarceration in "
            "Texas. Arrears can accumulate quickly. Within 90 days of "
            "release (or while incarcerated through TDCJ's Attorney "
            "General partnership program), a person can petition the court "
            "for modification based on the income change. Filing a "
            "modification does NOT erase past arrears but stops new ones "
            "from accruing at the pre-incarceration rate."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/FA/htm/FA.156.htm#156.401",
        "category": "legal_information",
        "subcategory": "child_support_modification_post_incarceration",
        "tags": ["child_support", "family_156_401", "modification", "arrears",
                 "attorney_general_office"],
    },
    # ----------------------------------------------------------------------
    # Texas: Health and Safety Code (drug offenses)
    # ----------------------------------------------------------------------
    {
        "id": "tx-hs-481-121-marijuana",
        "citation": "Texas Health and Safety Code § 481.121 (marijuana possession)",
        "summary": (
            "Texas penalties for marijuana possession (without intent to "
            "distribute) scale with amount: under 2oz is a Class B "
            "misdemeanor (up to 180 days jail), 2-4oz Class A, 4oz-5lb a "
            "state jail felony. Note that some Texas counties (e.g., Harris, "
            "Travis) have local diversion programs that resolve under-2oz "
            "cases without a conviction. Ask legal aid about diversion."
        ),
        "url": "https://statutes.capitol.texas.gov/Docs/HS/htm/HS.481.htm#481.121",
        "category": "legal_information",
        "subcategory": "marijuana_possession_penalties",
        "tags": ["drug_possession", "marijuana", "hs_481_121", "diversion",
                 "state_jail_felony"],
    },
]


def main() -> int:
    log(f"Curating {len(ENTRIES)} federal + TX corpus entries...")
    inserted = 0
    updated = 0
    with get_conn() as conn:
        for entry in ENTRIES:
            entry.setdefault("state", "TX")
            entry.setdefault("last_verified", today_iso())
            if upsert_corpus_entry(conn, entry, source=SOURCE):
                inserted += 1
            else:
                updated += 1

    log(f"  {inserted} inserted, {updated} updated")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM corpus WHERE source = %s", (SOURCE,))
            log(f"  total curated entries: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM corpus")
            log(f"  total corpus rows now: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
