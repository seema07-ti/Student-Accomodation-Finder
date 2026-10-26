import random
import json
from datetime import datetime, timedelta
from bson import ObjectId


# to get a random date and time between start and end date

def random_date(start, end):
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, seconds))


# changing python date into mongodb date format
# so it gets saved as a proper date in mongodb and not as a string

def mongo_date(d):
    return {"$date": d.strftime("%Y-%m-%dT%H:%M:%SZ")}


# to make a new unique mongodb id

def new_id():
    return {"$oid": str(ObjectId())}


# to make a random uk mobile number

def make_phone():
    return "+44 7" + str(random.randint(100, 999)) + " " + str(random.randint(100000, 999999))


def generate_data():

    today = datetime(2026, 10, 26)   # fixed date so all the dates are based on today

    # campuses with their streets, postcodes and min/max weekly rent in £
    campuses = [
        {"campus": "Belfast", "city": "Belfast",
         "streets": ["Botanic Avenue", "Malone Road", "Ormeau Road", "University Street", "York Street", "Antrim Road"],
         "postcodes": ["BT1", "BT7", "BT9", "BT15"],
         "min_rent": 95, "max_rent": 180},
        {"campus": "Coleraine", "city": "Coleraine",
         "streets": ["Portstewart Road", "Lodge Road", "Mountsandel Road", "Railway Road"],
         "postcodes": ["BT51", "BT52"],
         "min_rent": 75, "max_rent": 140},
        {"campus": "Derry~Londonderry", "city": "Derry~Londonderry",
         "streets": ["Strand Road", "Northland Road", "Great James Street", "Clarendon Street"],
         "postcodes": ["BT48"],
         "min_rent": 70, "max_rent": 130},
    ]

    # types of property and how many rooms each type can have
    property_types = [
        {"type": "House share", "min_rooms": 3, "max_rooms": 6},
        {"type": "Studio", "min_rooms": 1, "max_rooms": 1},
        {"type": "Apartment", "min_rooms": 1, "max_rooms": 3},
        {"type": "Purpose-built halls", "min_rooms": 4, "max_rooms": 8},
    ]

    # possible amenities
    amenity_options = ["WiFi", "Parking", "Garden", "Gym", "Washing machine",
                       "Dishwasher", "Bike storage", "Study room", "CCTV"]

    # possible room status, put available 3 times so more rooms come as available
    room_statuses = ["available", "available", "available", "reserved", "let", "let"]

    # possible landlord first and last names
    landlord_first = ["Michael", "Siobhan", "David", "Karen", "Paul", "Mary", "Brian", "Anne", "Gerard", "Helen"]
    landlord_last = ["McAllister", "Devlin", "Stewart", "Kerr", "Boyle", "McLaughlin", "Graham", "Mulholland"]

    property_list = []   # space for property list

    # to create 125 properties
    for i in range(125):
        # picking campus, type, bills and landlord again for every new property
        location = random.choice(campuses)
        prop_type = random.choice(property_types)
        bills_included = random.choice([True, False])
        landlord_name = random.choice(landlord_first) + " " + random.choice(landlord_last)

        # making the rooms list for this property
        rooms = []
        number_of_rooms = random.randint(prop_type["min_rooms"], prop_type["max_rooms"])
        for r in range(number_of_rooms):
            # studio is always one room with its own bathroom
            if prop_type["type"] == "Studio":
                room_type = "Studio"
                ensuite = True
            else:
                room_type = random.choice(["Single", "Double"])
                ensuite = random.choice([True, False])

            # rent from the campus range, then add extra for ensuite and bills
            rent = random.randint(location["min_rent"], location["max_rent"])
            if ensuite:
                rent = rent + 10          # extra £10 for ensuite
            if bills_included:
                rent = rent + 15          # extra £15 if bills are included

            status = random.choice(room_statuses)

            # available from date only for available rooms, others stay null
            if status == "available":
                available_from = mongo_date(random_date(today, today + timedelta(days=90)))
            else:
                available_from = None

            # to insert each room into the rooms list
            rooms.append({
                "_id": new_id(),
                "room_number": "R" + str(r + 1),
                "room_type": room_type,
                "rent_per_week": rent,
                "ensuite": ensuite,
                "room_status": status,
                "available_from": available_from
            })

        # to insert property details as a dictionary into the list
        property_list.append({
            "property_id": "PRP" + str(i + 1).zfill(3),   # PRP001, PRP002...
            "title": str(number_of_rooms) + "-room " + prop_type["type"].lower() + " near " + location["campus"] + " campus",
            "property_type": prop_type["type"],
            "address": {
                "street": str(random.randint(1, 150)) + " " + random.choice(location["streets"]),
                "city": location["city"],
                # postcode like BT7 1AB
                "postcode": random.choice(location["postcodes"]) + " " + str(random.randint(1, 9)) + random.choice("ABDEFGHJLNPQRSTUWXYZ") + random.choice("ABDEFGHJLNPQRSTUWXYZ")
            },
            "nearest_campus": location["campus"],
            "distance_to_campus_km": round(random.uniform(0.2, 5.0), 1),
            "landlord": {
                "name": landlord_name,
                "email": landlord_name.lower().replace(" ", ".") + "@example.com",
                "phone": make_phone()
            },
            "bills_included": bills_included,
            "amenities": random.sample(amenity_options, random.randint(2, 5)),
            "rooms": rooms,
            "reviews": [],          # empty for now, will add reviews when making applications
            "recent_update": mongo_date(random_date(today - timedelta(days=60), today))
        })

    return property_list


properties = generate_data()  # calling function to run it

# saving the list into properties.json file
with open('properties.json', 'w', encoding="utf-8") as fout:
    json.dump(properties, fout, indent=4)