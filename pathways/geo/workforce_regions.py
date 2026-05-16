"""Texas Workforce Commission 28 workforce region mapping.

TWC operates through 28 local Workforce Development Boards covering all
254 Texas counties. The region a person lives in determines which
workforce solutions office serves them, which reentry program funding
streams apply, and (for some county-level programs) which courthouse
they file in.

Source: twc.texas.gov, public Workforce Development Board service area
documentation. This map is updated rarely; the last refresh date is
recorded in `LAST_VERIFIED` below so the weekly resource-refresh job
can flag drift.

To use:
    from pathways.geo.workforce_regions import COUNTY_TO_REGION
    region = COUNTY_TO_REGION.get(county_name.title())   # e.g. "Harris" -> "Gulf Coast"
"""

LAST_VERIFIED = "2026-05-16"

# The 28 TWC workforce regions.
REGIONS = (
    "Panhandle", "South Plains", "North Texas", "North Central",
    "Tarrant County", "Dallas", "Northeast Texas", "East Texas",
    "West Central", "Borderplex", "Permian Basin", "Concho Valley",
    "Heart of Texas", "Capital Area", "Rural Capital", "Brazos Valley",
    "Deep East Texas", "Southeast Texas", "Golden Crescent", "Alamo",
    "South Texas", "Coastal Bend", "Lower Rio Grande Valley",
    "Cameron County", "Texoma", "Central Texas", "Middle Rio Grande",
    "Gulf Coast",
)

# Authoritative county -> region map. Counties typed in alpha order.
# Note: a small number of counties span multiple boards in practice but
# the primary workforce development board is canonical.
COUNTY_TO_REGION: dict[str, str] = {
    "Anderson": "Deep East Texas", "Andrews": "Permian Basin", "Angelina": "Deep East Texas",
    "Aransas": "Coastal Bend", "Archer": "North Texas", "Armstrong": "Panhandle",
    "Atascosa": "Alamo", "Austin": "Gulf Coast", "Bailey": "South Plains",
    "Bandera": "Alamo", "Bastrop": "Rural Capital", "Baylor": "North Texas",
    "Bee": "Coastal Bend", "Bell": "Central Texas", "Bexar": "Alamo",
    "Blanco": "Capital Area", "Borden": "Permian Basin", "Bosque": "Heart of Texas",
    "Bowie": "Northeast Texas", "Brazoria": "Gulf Coast", "Brazos": "Brazos Valley",
    "Brewster": "Permian Basin", "Briscoe": "Panhandle", "Brooks": "South Texas",
    "Brown": "West Central", "Burleson": "Brazos Valley", "Burnet": "Rural Capital",
    "Caldwell": "Rural Capital", "Calhoun": "Golden Crescent", "Callahan": "West Central",
    "Cameron": "Cameron County", "Camp": "Northeast Texas", "Carson": "Panhandle",
    "Cass": "Northeast Texas", "Castro": "Panhandle", "Chambers": "Gulf Coast",
    "Cherokee": "Deep East Texas", "Childress": "Panhandle", "Clay": "North Texas",
    "Cochran": "South Plains", "Coke": "Concho Valley", "Coleman": "West Central",
    "Collin": "North Central", "Collingsworth": "Panhandle", "Colorado": "Gulf Coast",
    "Comal": "Alamo", "Comanche": "West Central", "Concho": "Concho Valley",
    "Cooke": "North Central", "Coryell": "Central Texas", "Cottle": "South Plains",
    "Crane": "Permian Basin", "Crockett": "Concho Valley", "Crosby": "South Plains",
    "Culberson": "Borderplex", "Dallam": "Panhandle", "Dallas": "Dallas",
    "Dawson": "Permian Basin", "Deaf Smith": "Panhandle", "Delta": "Northeast Texas",
    "Denton": "North Central", "DeWitt": "Golden Crescent", "Dickens": "South Plains",
    "Dimmit": "Middle Rio Grande", "Donley": "Panhandle", "Duval": "South Texas",
    "Eastland": "West Central", "Ector": "Permian Basin", "Edwards": "Middle Rio Grande",
    "El Paso": "Borderplex", "Ellis": "North Central", "Erath": "North Central",
    "Falls": "Heart of Texas", "Fannin": "North Central", "Fayette": "Rural Capital",
    "Fisher": "West Central", "Floyd": "South Plains", "Foard": "North Texas",
    "Fort Bend": "Gulf Coast", "Franklin": "Northeast Texas", "Freestone": "Heart of Texas",
    "Frio": "Alamo", "Gaines": "Permian Basin", "Galveston": "Gulf Coast",
    "Garza": "South Plains", "Gillespie": "Alamo", "Glasscock": "Permian Basin",
    "Goliad": "Golden Crescent", "Gonzales": "Golden Crescent", "Gray": "Panhandle",
    "Grayson": "Texoma", "Gregg": "East Texas", "Grimes": "Brazos Valley",
    "Guadalupe": "Alamo", "Hale": "South Plains", "Hall": "Panhandle",
    "Hamilton": "Heart of Texas", "Hansford": "Panhandle", "Hardeman": "North Texas",
    "Hardin": "Southeast Texas", "Harris": "Gulf Coast", "Harrison": "East Texas",
    "Hartley": "Panhandle", "Haskell": "West Central", "Hays": "Rural Capital",
    "Hemphill": "Panhandle", "Henderson": "East Texas", "Hidalgo": "Lower Rio Grande Valley",
    "Hill": "Heart of Texas", "Hockley": "South Plains", "Hood": "North Central",
    "Hopkins": "Northeast Texas", "Houston": "Deep East Texas", "Howard": "Permian Basin",
    "Hudspeth": "Borderplex", "Hunt": "North Central", "Hutchinson": "Panhandle",
    "Irion": "Concho Valley", "Jack": "North Central", "Jackson": "Golden Crescent",
    "Jasper": "Deep East Texas", "Jeff Davis": "Permian Basin", "Jefferson": "Southeast Texas",
    "Jim Hogg": "South Texas", "Jim Wells": "Coastal Bend", "Johnson": "North Central",
    "Jones": "West Central", "Karnes": "Alamo", "Kaufman": "North Central",
    "Kendall": "Alamo", "Kenedy": "South Texas", "Kent": "West Central",
    "Kerr": "Alamo", "Kimble": "Concho Valley", "King": "South Plains",
    "Kinney": "Middle Rio Grande", "Kleberg": "Coastal Bend", "Knox": "North Texas",
    "Lamar": "Northeast Texas", "Lamb": "South Plains", "Lampasas": "Central Texas",
    "La Salle": "Middle Rio Grande", "Lavaca": "Golden Crescent", "Lee": "Rural Capital",
    "Leon": "Brazos Valley", "Liberty": "Gulf Coast", "Limestone": "Heart of Texas",
    "Lipscomb": "Panhandle", "Live Oak": "Coastal Bend", "Llano": "Rural Capital",
    "Loving": "Permian Basin", "Lubbock": "South Plains", "Lynn": "South Plains",
    "Madison": "Brazos Valley", "Marion": "East Texas", "Martin": "Permian Basin",
    "Mason": "Alamo", "Matagorda": "Gulf Coast", "Maverick": "Middle Rio Grande",
    "McCulloch": "Concho Valley", "McLennan": "Heart of Texas", "McMullen": "Coastal Bend",
    "Medina": "Alamo", "Menard": "Concho Valley", "Midland": "Permian Basin",
    "Milam": "Rural Capital", "Mills": "West Central", "Mitchell": "West Central",
    "Montague": "North Texas", "Montgomery": "Gulf Coast", "Moore": "Panhandle",
    "Morris": "Northeast Texas", "Motley": "South Plains", "Nacogdoches": "Deep East Texas",
    "Navarro": "North Central", "Newton": "Deep East Texas", "Nolan": "West Central",
    "Nueces": "Coastal Bend", "Ochiltree": "Panhandle", "Oldham": "Panhandle",
    "Orange": "Southeast Texas", "Palo Pinto": "North Central", "Panola": "East Texas",
    "Parker": "North Central", "Parmer": "Panhandle", "Pecos": "Permian Basin",
    "Polk": "Deep East Texas", "Potter": "Panhandle", "Presidio": "Permian Basin",
    "Rains": "Northeast Texas", "Randall": "Panhandle", "Reagan": "Concho Valley",
    "Real": "Middle Rio Grande", "Red River": "Northeast Texas", "Reeves": "Permian Basin",
    "Refugio": "Golden Crescent", "Roberts": "Panhandle", "Robertson": "Brazos Valley",
    "Rockwall": "North Central", "Runnels": "Concho Valley", "Rusk": "East Texas",
    "Sabine": "Deep East Texas", "San Augustine": "Deep East Texas",
    "San Jacinto": "Gulf Coast", "San Patricio": "Coastal Bend", "San Saba": "Concho Valley",
    "Schleicher": "Concho Valley", "Scurry": "West Central", "Shackelford": "West Central",
    "Shelby": "Deep East Texas", "Sherman": "Panhandle", "Smith": "East Texas",
    "Somervell": "North Central", "Starr": "Lower Rio Grande Valley", "Stephens": "West Central",
    "Sterling": "Concho Valley", "Stonewall": "West Central", "Sutton": "Concho Valley",
    "Swisher": "Panhandle", "Tarrant": "Tarrant County", "Taylor": "West Central",
    "Terrell": "Concho Valley", "Terry": "South Plains", "Throckmorton": "West Central",
    "Titus": "Northeast Texas", "Tom Green": "Concho Valley", "Travis": "Capital Area",
    "Trinity": "Deep East Texas", "Tyler": "Deep East Texas", "Upshur": "East Texas",
    "Upton": "Permian Basin", "Uvalde": "Middle Rio Grande", "Val Verde": "Middle Rio Grande",
    "Van Zandt": "East Texas", "Victoria": "Golden Crescent", "Walker": "Gulf Coast",
    "Waller": "Gulf Coast", "Ward": "Permian Basin", "Washington": "Brazos Valley",
    "Webb": "South Texas", "Wharton": "Gulf Coast", "Wheeler": "Panhandle",
    "Wichita": "North Texas", "Wilbarger": "North Texas", "Willacy": "Cameron County",
    "Williamson": "Rural Capital", "Wilson": "Alamo", "Winkler": "Permian Basin",
    "Wise": "North Central", "Wood": "East Texas", "Yoakum": "South Plains",
    "Young": "North Central", "Zapata": "South Texas", "Zavala": "Middle Rio Grande",
}

assert len(COUNTY_TO_REGION) == 254, (
    f"Expected 254 TX counties, found {len(COUNTY_TO_REGION)}"
)
assert set(COUNTY_TO_REGION.values()).issubset(set(REGIONS)), (
    f"Unknown regions in map: {set(COUNTY_TO_REGION.values()) - set(REGIONS)}"
)
