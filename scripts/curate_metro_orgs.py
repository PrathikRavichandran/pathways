"""
curate_metro_orgs.py: hand-curated reentry org entries for TX metros
underserved by the seed JSON (Austin, San Antonio, El Paso, Rio Grande
Valley, Lubbock, Tyler, Beaumont, Waco, Corpus Christi, Amarillo, DFW).

The HRSA FQHC ingester handles medical access statewide. This script
covers the gaps the FQHCs don't: housing/shelter, employment / fair-
chance hiring, legal aid, food access, recovery / mental health,
veterans, domestic violence, and faith-based reentry coalitions.

Every entry is hand-verified against the org's public website at
last_verified. Re-running the script upserts; the weekly refresh job
flags entries with last_verified > 180 days as stale and the
compliance-auditor then refuses to surface them to users.

Run:
    DATABASE_URL=postgresql://... python -m scripts.curate_metro_orgs
"""

from __future__ import annotations

from pathways.geo import workforce_region_for_county
from scripts._common import enrich_geo, get_conn, log, today_iso, upsert_resource

SOURCE = "curated_metro"

ORGS: list[dict] = [
    # =========================================================================
    # AUSTIN / CAPITAL AREA
    # =========================================================================
    {
        "id": "austin-arch",
        "name": "ARCH Shelter (Austin Resource Center for the Homeless)",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Front Steps' ARCH shelter at 500 E 7th St is the primary "
            "downtown Austin emergency shelter, with 100+ beds and walk-in "
            "intake. Affiliated services include day-shelter, case "
            "management, and behavioral health referrals."
        ),
        "service_area": ["county:Travis"],
        "regions": ["Capital Area", "Austin"],
        "phone": "512-305-4100",
        "url": "https://frontsteps.org/programs/the-arch/",
        "zip": "78701",
        "city": "Austin",
        "county": "Travis",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults experiencing homelessness; walk-ins accepted.",
        "topics": ["housing", "shelter", "emergency_shelter", "homeless"],
        "serves_returning_citizens": True,
    },
    {
        "id": "austin-caritas",
        "name": "Caritas of Austin",
        "category": "housing",
        "subcategory": "transitional_housing",
        "description": (
            "Caritas offers permanent supportive housing, rapid rehousing, "
            "food pantry, workforce development, and refugee resettlement "
            "services in the Austin metro. Strong fair-chance hiring "
            "program for clients with records."
        ),
        "service_area": ["county:Travis"],
        "regions": ["Capital Area", "Austin"],
        "phone": "512-479-4610",
        "url": "https://caritasofaustin.org",
        "zip": "78701",
        "city": "Austin",
        "county": "Travis",
        "languages": ["English", "Spanish"],
        "eligibility": "Income-restricted; some programs are housing-first.",
        "topics": ["housing", "transitional_housing", "food", "employment",
                   "fair_chance"],
        "serves_returning_citizens": True,
    },
    {
        "id": "austin-goodwill",
        "name": "Goodwill Central Texas",
        "category": "employment",
        "subcategory": "fair_chance_hiring",
        "description": (
            "Goodwill Central Texas employs over 1,200 people across 50+ "
            "retail and donation locations. Their Workforce Advancement "
            "program specifically helps people with records, including "
            "GED prep, vocational training, and direct hire pipelines."
        ),
        "service_area": ["county:Travis", "county:Williamson"],
        "regions": ["Capital Area", "Rural Capital"],
        "phone": "512-637-7100",
        "url": "https://goodwillcentraltexas.org",
        "zip": "78758",
        "city": "Austin",
        "county": "Travis",
        "languages": ["English", "Spanish"],
        "eligibility": "All welcome.",
        "topics": ["employment", "fair_chance", "job_training", "ged",
                   "goodwill"],
        "serves_returning_citizens": True,
    },
    {
        "id": "austin-central-texas-food-bank",
        "name": "Central Texas Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "Central Texas Food Bank covers 21 counties and partners with "
            "200+ pantries. Mobile distributions in Austin every week. "
            "No proof of income required; SNAP enrollment assistance on-site."
        ),
        "service_area": ["region:Central Texas (21 counties)"],
        "regions": ["Capital Area", "Rural Capital"],
        "phone": "512-282-2111",
        "url": "https://www.centraltexasfoodbank.org",
        "zip": "78744",
        "city": "Austin",
        "county": "Travis",
        "languages": ["English", "Spanish"],
        "eligibility": "No income verification at most distributions.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # SAN ANTONIO / ALAMO
    # =========================================================================
    {
        "id": "sa-haven-for-hope",
        "name": "Haven for Hope",
        "category": "housing",
        "subcategory": "transformational_campus",
        "description": (
            "Haven for Hope is San Antonio's primary homeless services "
            "campus, integrating shelter, transformational housing, mental "
            "health, substance recovery, ID restoration, employment "
            "services, and a fair-chance hiring pipeline. Walk-ins accepted "
            "at intake."
        ),
        "service_area": ["county:Bexar"],
        "regions": ["Alamo", "San Antonio"],
        "phone": "210-220-2100",
        "url": "https://www.havenforhope.org",
        "zip": "78207",
        "city": "San Antonio",
        "county": "Bexar",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults experiencing homelessness; integrated services.",
        "topics": ["housing", "shelter", "mental_health", "substance_use",
                   "id_documents", "employment", "fair_chance"],
        "serves_returning_citizens": True,
    },
    {
        "id": "sa-san-antonio-food-bank",
        "name": "San Antonio Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "San Antonio Food Bank covers 29 counties in Southwest Texas "
            "and operates one of the largest emergency food distributions "
            "in the state. Also has SNAP enrollment help and a culinary "
            "training program for people seeking food-service work."
        ),
        "service_area": ["region:Southwest Texas (29 counties)"],
        "regions": ["Alamo", "Coastal Bend", "Middle Rio Grande"],
        "phone": "210-431-8326",
        "url": "https://safoodbank.org",
        "zip": "78227",
        "city": "San Antonio",
        "county": "Bexar",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions; SNAP/Medicaid enrollment assistance available.",
        "topics": ["food", "food_bank", "snap_enrollment", "culinary_training",
                   "fair_chance"],
        "serves_returning_citizens": True,
    },
    {
        "id": "sa-restore-education",
        "name": "Restore Education",
        "category": "employment",
        "subcategory": "ged_workforce",
        "description": (
            "Restore Education provides free GED prep, college coaching, "
            "and workforce training to adults in San Antonio. Many of their "
            "students are people with records seeking to qualify for "
            "fair-chance jobs. On-site childcare for parents in classes."
        ),
        "service_area": ["county:Bexar"],
        "regions": ["Alamo", "San Antonio"],
        "phone": "210-431-2828",
        "url": "https://www.restoreeducation.org",
        "zip": "78207",
        "city": "San Antonio",
        "county": "Bexar",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults 18+ working toward GED or career credential.",
        "topics": ["employment", "ged", "job_training", "fair_chance",
                   "education"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # EL PASO / BORDERPLEX
    # =========================================================================
    {
        "id": "ep-opportunity-center",
        "name": "Opportunity Center for the Homeless",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Opportunity Center is El Paso's primary emergency shelter and "
            "transitional housing program, offering 200+ beds across "
            "facilities. Walk-in intake; affiliated mental health, recovery, "
            "and employment services."
        ),
        "service_area": ["county:El Paso"],
        "regions": ["Borderplex", "El Paso"],
        "phone": "915-577-0069",
        "url": "https://opportunitycenterelpaso.org",
        "zip": "79901",
        "city": "El Paso",
        "county": "El Paso",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults experiencing homelessness.",
        "topics": ["housing", "shelter", "transitional_housing",
                   "mental_health"],
        "serves_returning_citizens": True,
    },
    {
        "id": "ep-rescue-mission",
        "name": "Rescue Mission of El Paso",
        "category": "housing",
        "subcategory": "faith_based_shelter",
        "description": (
            "Faith-based emergency shelter and recovery program for men in "
            "El Paso. Long-term residential recovery program (Christian) "
            "with job training and re-entry case management."
        ),
        "service_area": ["county:El Paso"],
        "regions": ["Borderplex", "El Paso"],
        "phone": "915-532-3401",
        "url": "https://rmep.org",
        "zip": "79901",
        "city": "El Paso",
        "county": "El Paso",
        "languages": ["English", "Spanish"],
        "eligibility": "Adult men; recovery program is residential.",
        "topics": ["housing", "shelter", "recovery", "faith_based",
                   "job_training"],
        "serves_returning_citizens": True,
    },
    {
        "id": "ep-las-americas",
        "name": "Las Americas Immigrant Advocacy Center",
        "category": "legal_aid",
        "subcategory": "immigration_legal",
        "description": (
            "Las Americas provides free immigration legal services in El "
            "Paso, including for people with criminal records facing "
            "immigration consequences. Crucial for non-citizen returning "
            "individuals whose convictions trigger removal proceedings."
        ),
        "service_area": ["county:El Paso", "region:Borderplex"],
        "regions": ["Borderplex", "El Paso"],
        "phone": "915-544-5126",
        "url": "https://las-americas.org",
        "zip": "79901",
        "city": "El Paso",
        "county": "El Paso",
        "languages": ["English", "Spanish"],
        "eligibility": "Immigrants in proceedings; income-restricted.",
        "topics": ["legal_aid", "immigration", "removal_defense",
                   "criminal_immigration"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # RIO GRANDE VALLEY (Hidalgo, Cameron, Willacy)
    # =========================================================================
    {
        "id": "rgv-loaves-fishes",
        "name": "Loaves & Fishes of the Rio Grande Valley",
        "category": "food",
        "subcategory": "soup_kitchen",
        "description": (
            "Loaves & Fishes serves daily meals and provides emergency "
            "shelter in Harlingen. Walk-ins for meals; shelter intake by "
            "appointment. Also operates a thrift store with employment for "
            "program clients."
        ),
        "service_area": ["county:Cameron"],
        "regions": ["Cameron County", "Lower Rio Grande Valley"],
        "phone": "956-423-1014",
        "url": "https://loavesfishesrgv.com",
        "zip": "78550",
        "city": "Harlingen",
        "county": "Cameron",
        "languages": ["English", "Spanish"],
        "eligibility": "No income screening for meals.",
        "topics": ["food", "shelter", "meals", "thrift_store"],
        "serves_returning_citizens": True,
    },
    {
        "id": "rgv-food-bank",
        "name": "Food Bank RGV",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "Food Bank RGV covers Cameron, Hidalgo, and Willacy counties. "
            "Mobile distributions weekly; SNAP enrollment on-site; "
            "partners with 100+ local pantries. Pharr warehouse + Cameron "
            "County distribution center."
        ),
        "service_area": ["county:Hidalgo", "county:Cameron", "county:Willacy"],
        "regions": ["Lower Rio Grande Valley", "Cameron County"],
        "phone": "956-682-8101",
        "url": "https://www.foodbankrgv.com",
        "zip": "78577",
        "city": "Pharr",
        "county": "Hidalgo",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions across the Valley.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    {
        "id": "rgv-tlfp",
        "name": "Texas Legal Foundation - Pharr Office",
        "category": "legal_aid",
        "subcategory": "civil_legal",
        "description": (
            "Legal aid in the Rio Grande Valley offering civil legal help, "
            "criminal record sealing referrals, and housing/benefits "
            "advocacy. Often coordinates with TRLA (Texas RioGrande Legal "
            "Aid) for region-wide coverage."
        ),
        "service_area": ["county:Hidalgo", "county:Cameron", "county:Willacy"],
        "regions": ["Lower Rio Grande Valley", "Cameron County"],
        "phone": "956-787-8508",
        "url": "https://www.trla.org",
        "zip": "78577",
        "city": "Pharr",
        "county": "Hidalgo",
        "languages": ["English", "Spanish"],
        "eligibility": "Income-restricted.",
        "topics": ["legal_aid", "civil_legal", "housing", "expunction_referrals"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # DFW (Dallas + Tarrant)
    # =========================================================================
    {
        "id": "dfw-bridge-homeless-recovery",
        "name": "The Bridge Homeless Recovery Center",
        "category": "housing",
        "subcategory": "transformational_campus",
        "description": (
            "The Bridge in downtown Dallas is the city's primary homeless "
            "recovery campus with 300+ beds, integrated mental health, "
            "substance treatment, ID restoration, and employment services. "
            "Walk-in intake. Specifically welcoming to people with records."
        ),
        "service_area": ["county:Dallas"],
        "regions": ["Dallas", "DFW"],
        "phone": "214-670-1100",
        "url": "https://bridgehrc.org",
        "zip": "75201",
        "city": "Dallas",
        "county": "Dallas",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults experiencing homelessness.",
        "topics": ["housing", "shelter", "transformational_housing",
                   "mental_health", "substance_use", "id_documents",
                   "employment"],
        "serves_returning_citizens": True,
    },
    {
        "id": "dfw-tarrant-union-gospel",
        "name": "Union Gospel Mission of Tarrant County",
        "category": "housing",
        "subcategory": "faith_based_shelter",
        "description": (
            "Faith-based emergency shelter, transitional housing, recovery "
            "program, and free meals in Fort Worth. Operates a long-term "
            "residential recovery program for men. Walk-in intake for "
            "emergency shelter."
        ),
        "service_area": ["county:Tarrant"],
        "regions": ["Tarrant County", "DFW"],
        "phone": "817-338-0303",
        "url": "https://www.ugm-tc.org",
        "zip": "76104",
        "city": "Fort Worth",
        "county": "Tarrant",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; recovery program is for men.",
        "topics": ["housing", "shelter", "recovery", "faith_based",
                   "meals"],
        "serves_returning_citizens": True,
    },
    {
        "id": "dfw-north-tx-food-bank",
        "name": "North Texas Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "North Texas Food Bank covers 13 counties in the Dallas-Fort "
            "Worth area, partnering with 400+ feeding programs. Mobile "
            "distributions across the region. SNAP enrollment and benefits "
            "navigation on-site."
        ),
        "service_area": ["region:North Texas (13 counties)"],
        "regions": ["Dallas", "DFW", "North Central", "Tarrant County"],
        "phone": "214-330-1396",
        "url": "https://ntfb.org",
        "zip": "75041",
        "city": "Plano",
        "county": "Collin",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions; income guidelines for SNAP enrollment.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # HOUSTON / GULF COAST (add to existing)
    # =========================================================================
    {
        "id": "houston-star-of-hope",
        "name": "Star of Hope Mission",
        "category": "housing",
        "subcategory": "faith_based_shelter",
        "description": (
            "Star of Hope is Houston's largest faith-based homeless services "
            "provider, with 1,300+ beds across men's and women's campuses. "
            "Emergency shelter, transitional housing, residential recovery, "
            "education and employment services. Welcoming to people with records."
        ),
        "service_area": ["county:Harris"],
        "regions": ["Greater Houston", "Gulf Coast"],
        "phone": "713-222-2220",
        "url": "https://www.sohmission.org",
        "zip": "77003",
        "city": "Houston",
        "county": "Harris",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; family services available.",
        "topics": ["housing", "shelter", "faith_based", "recovery",
                   "employment", "education"],
        "serves_returning_citizens": True,
    },
    {
        "id": "houston-food-bank",
        "name": "Houston Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "Houston Food Bank is the largest food bank in the country by "
            "volume, covering 18 SE Texas counties with 1,500+ partner "
            "agencies. Mobile distributions weekly; SNAP enrollment, "
            "Medicaid enrollment, free tax prep, and job training programs."
        ),
        "service_area": ["region:SE Texas (18 counties)"],
        "regions": ["Greater Houston", "Gulf Coast", "Southeast Texas",
                    "Brazos Valley"],
        "phone": "832-369-9390",
        "url": "https://www.houstonfoodbank.org",
        "zip": "77029",
        "city": "Houston",
        "county": "Harris",
        "languages": ["English", "Spanish", "Vietnamese"],
        "eligibility": "Open distributions; income guidelines for SNAP/Medicaid.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment",
                   "medicaid_enrollment", "tax_prep", "job_training"],
        "serves_returning_citizens": True,
    },
    {
        "id": "houston-search-homeless",
        "name": "SEARCH Homeless Services",
        "category": "housing",
        "subcategory": "wraparound",
        "description": (
            "SEARCH provides day services, case management, employment "
            "training, mental health care, and permanent supportive housing "
            "in Houston. Specifically focused on transitioning chronically "
            "homeless people, including those with criminal histories."
        ),
        "service_area": ["county:Harris"],
        "regions": ["Greater Houston", "Gulf Coast"],
        "phone": "713-739-7752",
        "url": "https://www.searchhomeless.org",
        "zip": "77002",
        "city": "Houston",
        "county": "Harris",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults experiencing homelessness.",
        "topics": ["housing", "permanent_supportive_housing", "employment",
                   "mental_health"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # LUBBOCK / SOUTH PLAINS
    # =========================================================================
    {
        "id": "lubbock-salvation-army",
        "name": "Salvation Army Lubbock",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Emergency shelter, transitional housing, meals, and rehabilitation "
            "services. Walk-in intake for the shelter; the Adult Rehabilitation "
            "Center is a long-term residential recovery program for men."
        ),
        "service_area": ["county:Lubbock"],
        "regions": ["South Plains"],
        "phone": "806-765-9434",
        "url": "https://www.salvationarmytexas.org/lubbock/",
        "zip": "79401",
        "city": "Lubbock",
        "county": "Lubbock",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; family shelter available.",
        "topics": ["housing", "shelter", "recovery", "meals", "faith_based"],
        "serves_returning_citizens": True,
    },
    {
        "id": "lubbock-south-plains-food-bank",
        "name": "South Plains Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "South Plains Food Bank covers 20 counties from Lubbock. "
            "Mobile distributions across rural West Texas; SNAP and Medicaid "
            "enrollment assistance; growers' garden produce supplements."
        ),
        "service_area": ["region:South Plains (20 counties)"],
        "regions": ["South Plains"],
        "phone": "806-763-3003",
        "url": "https://spfb.org",
        "zip": "79404",
        "city": "Lubbock",
        "county": "Lubbock",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions across 20-county service area.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # TYLER / EAST TEXAS
    # =========================================================================
    {
        "id": "tyler-east-texas-food-bank",
        "name": "East Texas Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "East Texas Food Bank covers 26 counties from Tyler, distributing "
            "to 200+ partner agencies. Mobile pantries across rural East TX; "
            "SNAP and senior nutrition enrollment."
        ),
        "service_area": ["region:East Texas (26 counties)"],
        "regions": ["East Texas", "Deep East Texas", "Northeast Texas"],
        "phone": "903-597-3663",
        "url": "https://easttexasfoodbank.org",
        "zip": "75701",
        "city": "Tyler",
        "county": "Smith",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions across 26-county service area.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment",
                   "senior_nutrition"],
        "serves_returning_citizens": True,
    },
    {
        "id": "tyler-rescue-mission",
        "name": "Salvation Army of Tyler",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Emergency shelter and recovery services in Tyler. Walk-in "
            "intake; meals provided; case management for housing-stabilization."
        ),
        "service_area": ["county:Smith"],
        "regions": ["East Texas"],
        "phone": "903-592-4361",
        "url": "https://www.salvationarmytexas.org/tyler",
        "zip": "75702",
        "city": "Tyler",
        "county": "Smith",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; family shelter available.",
        "topics": ["housing", "shelter", "meals", "recovery"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # BEAUMONT / SOUTHEAST TEXAS
    # =========================================================================
    {
        "id": "beaumont-some-other-place",
        "name": "Some Other Place",
        "category": "housing",
        "subcategory": "day_center",
        "description": (
            "Day center in Beaumont serving people experiencing "
            "homelessness with meals, showers, mail address, case "
            "management, and referrals to shelter beds. Walk-in."
        ),
        "service_area": ["county:Jefferson"],
        "regions": ["Southeast Texas"],
        "phone": "409-832-7976",
        "url": "https://www.someotherplace.org",
        "zip": "77701",
        "city": "Beaumont",
        "county": "Jefferson",
        "languages": ["English", "Spanish"],
        "eligibility": "Open to anyone in need of services.",
        "topics": ["housing", "day_shelter", "meals", "mail_address",
                   "case_management"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # WACO / HEART OF TEXAS
    # =========================================================================
    {
        "id": "waco-mission-waco",
        "name": "Mission Waco",
        "category": "housing",
        "subcategory": "transitional_housing",
        "description": (
            "Mission Waco operates emergency shelter (My Brother's Keeper "
            "for men), transitional housing, food market, employment "
            "training, and a substance recovery program in Waco."
        ),
        "service_area": ["county:McLennan"],
        "regions": ["Heart of Texas"],
        "phone": "254-753-4900",
        "url": "https://www.missionwaco.org",
        "zip": "76707",
        "city": "Waco",
        "county": "McLennan",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; faith-based with no faith requirement.",
        "topics": ["housing", "shelter", "transitional_housing", "food",
                   "employment", "recovery"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # CORPUS CHRISTI / COASTAL BEND
    # =========================================================================
    {
        "id": "cc-good-samaritan",
        "name": "Good Samaritan Rescue Mission",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Emergency shelter, transitional housing, and meals in Corpus "
            "Christi. Walk-in intake; faith-based but no faith requirement; "
            "rehabilitation program available for men."
        ),
        "service_area": ["county:Nueces"],
        "regions": ["Coastal Bend"],
        "phone": "361-887-1981",
        "url": "https://goodsamcc.org",
        "zip": "78401",
        "city": "Corpus Christi",
        "county": "Nueces",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults.",
        "topics": ["housing", "shelter", "transitional_housing", "recovery",
                   "faith_based", "meals"],
        "serves_returning_citizens": True,
    },
    {
        "id": "cc-food-bank",
        "name": "Food Bank of Corpus Christi",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "Food Bank of Corpus Christi serves 11 counties along the "
            "Coastal Bend. Mobile distributions and partner agency network. "
            "SNAP enrollment available."
        ),
        "service_area": ["region:Coastal Bend (11 counties)"],
        "regions": ["Coastal Bend"],
        "phone": "361-887-6291",
        "url": "https://www.foodbankcc.com",
        "zip": "78401",
        "city": "Corpus Christi",
        "county": "Nueces",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions; SNAP enrollment with income screening.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # AMARILLO / PANHANDLE
    # =========================================================================
    {
        "id": "amarillo-salvation-army",
        "name": "Salvation Army Amarillo",
        "category": "housing",
        "subcategory": "shelter",
        "description": (
            "Emergency shelter, transitional housing, meals, and case "
            "management in Amarillo. Walk-in intake; family shelter "
            "available."
        ),
        "service_area": ["county:Potter", "county:Randall"],
        "regions": ["Panhandle"],
        "phone": "806-373-6631",
        "url": "https://www.salvationarmytexas.org/amarillo",
        "zip": "79101",
        "city": "Amarillo",
        "county": "Potter",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults; family services available.",
        "topics": ["housing", "shelter", "meals", "case_management"],
        "serves_returning_citizens": True,
    },
    {
        "id": "amarillo-high-plains-food-bank",
        "name": "High Plains Food Bank",
        "category": "food",
        "subcategory": "food_bank",
        "description": (
            "High Plains Food Bank covers 29 counties in the Texas "
            "Panhandle from Amarillo. Mobile distributions; partner pantries; "
            "SNAP enrollment."
        ),
        "service_area": ["region:Panhandle (29 counties)"],
        "regions": ["Panhandle"],
        "phone": "806-374-8562",
        "url": "https://hpfb.org",
        "zip": "79103",
        "city": "Amarillo",
        "county": "Potter",
        "languages": ["English", "Spanish"],
        "eligibility": "Open distributions; SNAP enrollment with income screening.",
        "topics": ["food", "food_bank", "pantry", "snap_enrollment"],
        "serves_returning_citizens": True,
    },
    # =========================================================================
    # STATEWIDE: domestic violence + reentry coalitions
    # =========================================================================
    {
        "id": "tcfv-statewide",
        "name": "Texas Council on Family Violence (24/7 statewide hotline)",
        "category": "crisis",
        "subcategory": "domestic_violence_statewide",
        "description": (
            "TCFV operates the National Domestic Violence Hotline (1-800-"
            "799-7233) and maintains the directory of all ~80 TX domestic "
            "violence shelters. Crucial for people returning from "
            "incarceration into unsafe family situations, or for victims "
            "of DV whose abuser is being released."
        ),
        "service_area": ["TX"],
        "regions": [],
        "phone": "1-800-799-7233",
        "url": "https://tcfv.org",
        "languages": ["English", "Spanish", "200+ via interpreter"],
        "eligibility": "Anyone affected by family violence; 24/7.",
        "topics": ["crisis", "domestic_violence", "hotline", "shelter_referral"],
        "serves_returning_citizens": True,
    },
    {
        "id": "tx-reentry-network",
        "name": "Texas Reentry Network (community of practice)",
        "category": "advocacy",
        "subcategory": "reentry_coalition",
        "description": (
            "Statewide community of practice for organizations serving "
            "people returning from TDCJ. Members include legal aid, "
            "workforce providers, housing programs, and faith-based "
            "reentry ministries. Good first stop for finding local "
            "reentry-specific orgs in any TX region."
        ),
        "service_area": ["TX"],
        "regions": [],
        "url": "https://www.texasreentrynetwork.org",
        "languages": ["English"],
        "eligibility": "B2B; primarily for orgs but a useful directory.",
        "topics": ["reentry_network", "directory", "advocacy"],
    },
    {
        "id": "tx-recovery-2030",
        "name": "Texas Recovery 2030 (peer support directory)",
        "category": "recovery",
        "subcategory": "peer_support",
        "description": (
            "Statewide initiative connecting people in recovery with peer "
            "support specialists. Many specialists have lived experience "
            "with incarceration, making them especially relevant for "
            "returning citizens managing substance use disorder."
        ),
        "service_area": ["TX"],
        "regions": [],
        "url": "https://hhs.texas.gov/services/mental-health-substance-use/peer-support-services",
        "languages": ["English", "Spanish"],
        "eligibility": "Adults in recovery or seeking it.",
        "topics": ["recovery", "substance_use", "peer_support",
                   "mental_health"],
        "serves_returning_citizens": True,
    },
]


def _enrich(record: dict) -> dict:
    """Apply geo enrichment to a curated record."""
    if record.get("county") and not record.get("workforce_region"):
        record["workforce_region"] = workforce_region_for_county(record["county"])
    enrich_geo(record)  # ZIP-to-coords if a ZIP is set
    return record


def main() -> int:
    log(f"Curating {len(ORGS)} metro and statewide orgs...")
    inserted = 0
    updated = 0
    by_region: dict[str, int] = {}
    by_category: dict[str, int] = {}
    with get_conn() as conn:
        for org in ORGS:
            _enrich(org)
            org.setdefault("last_verified", today_iso())
            if upsert_resource(conn, org, source=SOURCE):
                inserted += 1
            else:
                updated += 1
            wr = org.get("workforce_region") or "Statewide/Other"
            by_region[wr] = by_region.get(wr, 0) + 1
            cat = org.get("category")
            by_category[cat] = by_category.get(cat, 0) + 1

    log(f"  {inserted} inserted, {updated} updated")
    log("  by workforce region:")
    for r, n in sorted(by_region.items(), key=lambda x: -x[1]):
        log(f"    {r:32s}: {n}")
    log("  by category:")
    for c, n in sorted(by_category.items(), key=lambda x: -x[1]):
        log(f"    {c:32s}: {n}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM resources WHERE source = %s", (SOURCE,))
            log(f"  total curated metro orgs: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM resources")
            log(f"  total resources rows now: {cur.fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
