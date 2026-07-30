from app.services.ebay_client import (
    extract_customer_vehicle_details_from_ebay_order,
    normalize_vehicle_make,
    normalize_vehicle_model,
)


def test_compatibility_properties_used_when_present():
    raw_order = {
        "buyerCheckoutNotes": "Buyer's note: Item Id: X\nBuyer's Vehicle: Tesla Model 3 2021 Plug-in Hybrid EV-GAS",
        "lineItems": [
            {
                "compatibilityProperties": [
                    {"propertyName": "Make", "propertyValue": "Tesla"},
                    {"propertyName": "Model", "propertyValue": "Model 3"},
                    {"propertyName": "Year", "propertyValue": "2021"},
                    {"propertyName": "Type", "propertyValue": "Hybrid"},
                ]
            }
        ],
    }

    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Tesla"
    assert extracted["vehicle_model"] == "Model 3"
    assert extracted["vehicle_year"] == 2021
    assert extracted["vehicle_type"] == "PHEV"


def test_buyer_note_fallback_parses_make_model_year_en():
    raw_order = {
        "buyerCheckoutNotes": "Buyer's note: Item Id: X\nBuyer's Vehicle: Tesla Model 3 2021 Electric Motor Saloon EV AWD",
        "lineItems": [{"compatibilityProperties": []}],
    }

    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Tesla"
    assert extracted["vehicle_model"] == "Model 3"
    assert extracted["vehicle_year"] == 2021
    assert extracted["vehicle_type"] == "EV"


def test_buyer_note_fallback_strips_roman_generation_suffix():
    raw_order = {
        "buyerCheckoutNotes": "Buyer's note:\nArtikelnummer: 1\nFahrzeug des Käufers: Jeep Wrangler IV 2023 JL 2.0 4xe Plug-in-Hybrid 1995 ccm",
        "lineItems": [{"compatibilityProperties": []}],
    }

    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Jeep"
    assert extracted["vehicle_model"] == "Wrangler"
    assert extracted["vehicle_year"] == 2023
    assert extracted["vehicle_type"] == "PHEV"


def test_normalize_vehicle_model_strips_roman_generations():
    assert normalize_vehicle_model("Outlander III") == "Outlander"
    assert normalize_vehicle_model("Kuga III") == "Kuga"
    assert normalize_vehicle_model("Golf VIII") == "Golf"
    assert normalize_vehicle_model("XC60 II") == "XC60"
    assert normalize_vehicle_model("208 II") == "208"
    assert normalize_vehicle_model("308 SW III") == "308 SW"
    assert normalize_vehicle_model("Model 3") == "Model 3"
    assert normalize_vehicle_model("ID.3") == "ID.3"
    assert normalize_vehicle_model("INSTER") == "Inster"
    assert normalize_vehicle_model("Q4 E-TRON") == "Q4 e-tron"
    assert normalize_vehicle_model("V-Class") == "V-Class"
    assert normalize_vehicle_model("E-Class") == "E-Class"
    assert normalize_vehicle_model("E-class") == "E-Class"
    assert normalize_vehicle_model("EQA") == "EQA"
    assert normalize_vehicle_model("MX-30") == "MX-30"
    assert normalize_vehicle_model("Enyaq SUV") == "Enyaq"
    assert normalize_vehicle_model("Enyaq IV SUV") == "Enyaq"


def test_extract_strips_redundant_make_from_model():
    raw_order = {
        "buyerCheckoutNotes": None,
        "lineItems": [
            {
                "compatibilityProperties": [
                    {"propertyName": "Make", "propertyValue": "MG"},
                    {"propertyName": "Model", "propertyValue": "MG HS"},
                    {"propertyName": "Year", "propertyValue": "2022"},
                ]
            }
        ],
    }
    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "MG"
    assert extracted["vehicle_model"] == "HS"


def test_extract_keeps_mg_numeric_model():
    raw_order = {
        "buyerCheckoutNotes": None,
        "lineItems": [
            {
                "compatibilityProperties": [
                    {"propertyName": "Make", "propertyValue": "MG"},
                    {"propertyName": "Model", "propertyValue": "MG 4"},
                    {"propertyName": "Year", "propertyValue": "2023"},
                ]
            }
        ],
    }
    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "MG"
    assert extracted["vehicle_model"] == "MG 4"


def test_listing_title_fallback_when_no_buyer_vehicle():
    raw_order = {
        "buyerCheckoutNotes": None,
        "lineItems": [
            {
                "title": "HYUNDAI INSTER EV Ladekabel Typ 2 Schuko 10M Ladegerät E Auto Elektroauto 230V",
                "compatibilityProperties": [],
            }
        ],
    }
    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Hyundai"
    assert extracted["vehicle_model"] == "Inster"
    assert extracted["vehicle_source"] == "listingTitle"
    assert extracted["vehicle_type"] == "EV"


def test_listing_title_enyaq_strips_roman_iv():
    raw_order = {
        "buyerCheckoutNotes": None,
        "lineItems": [
            {
                "title": "SKODA ENYAQ IV EV Charging Cable Type 2 3 Pin Plug 5M 13A Home Charger Portable",
                "compatibilityProperties": [],
            }
        ],
    }
    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Skoda"
    assert extracted["vehicle_model"] == "Enyaq"
    assert extracted["vehicle_source"] == "listingTitle"


def test_buyer_vehicle_wins_over_listing_title():
    raw_order = {
        "buyerCheckoutNotes": "Buyer's note:\nBuyer's Vehicle: Skoda Superb 2019 Plug-In Hybrid Estate 1.4 TSI iV FWD",
        "lineItems": [
            {
                "title": "SKODA ENYAQ IV EV Charging Cable Type 2 3 Pin Plug 10M 13A Home Charger Portable",
                "compatibilityProperties": [],
            }
        ],
    }
    extracted = extract_customer_vehicle_details_from_ebay_order(raw_order)
    assert extracted["vehicle_make"] == "Skoda"
    assert extracted["vehicle_model"] == "Superb"
    assert extracted["vehicle_source"] == "buyerCheckoutNotes"


def test_listing_title_multi_model_takes_first():
    from app.services.ebay_client import _parse_vehicle_from_listing_title

    parsed = _parse_vehicle_from_listing_title(
        "PEUGEOT 2008 3008 5008 PHEV EV Charger Cable Type 2 to Type 2 32A 5M 7kW Lead"
    )
    assert parsed["vehicle_make"] == "Peugeot"
    assert parsed["vehicle_model"] == "2008"


def test_listing_title_land_rover_range_rover():
    from app.services.ebay_client import _parse_vehicle_from_listing_title

    parsed = _parse_vehicle_from_listing_title(
        "LAND ROVER RANGE ROVER EVOQUE PHEV EV Charging Cable Type 2 3 Pin Plug 5M 13A"
    )
    assert parsed["vehicle_make"] == "Land Rover"
    assert parsed["vehicle_model"] == "Range Rover Evoque"


def test_normalize_vehicle_make_case_and_aliases():
    assert normalize_vehicle_make("KIA") == "Kia"
    assert normalize_vehicle_make("kia") == "Kia"
    assert normalize_vehicle_make("Mercedes Benz") == "Mercedes-Benz"
    assert normalize_vehicle_make("bmw") == "BMW"
