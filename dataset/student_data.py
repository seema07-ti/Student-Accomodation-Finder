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

    # possible first names
    first_names = ['Aoife', 'Ciara', 'Niamh', 'Grace', 'Emma', 'Sophie', 'Erin', 'Orla', 'Priya', 'Fatima',
                   'Conor', 'Sean', 'Patrick', 'Jack', 'James', 'Ryan', 'Daniel', 'Liam', 'Arjun', 'Tomasz']

    # possible last names
    last_names = ['Murphy', 'Kelly', "O'Neill", 'Doherty', 'Campbell', 'Wilson', 'Smith', 'Brown',
                  'Thompson', 'Quinn', 'Gallagher', 'McCann', 'Hughes', 'Patel', 'Sharma', 'Nowak']

    # home towns with postcodes (where student lives with family)
    towns = [
        {"city": "Belfast", "postcodes": ["BT5", "BT12", "BT14"]},
        {"city": "Lisburn", "postcodes": ["BT27", "BT28"]},
        {"city": "Newry", "postcodes": ["BT34", "BT35"]},
        {"city": "Omagh", "postcodes": ["BT78", "BT79"]},
        {"city": "Enniskillen", "postcodes": ["BT74"]},
        {"city": "Ballymena", "postcodes": ["BT42", "BT43"]},
        {"city": "Armagh", "postcodes": ["BT60", "BT61"]},
    ]

    # possible street names for home address
    streets = ['Main Street', 'High Street', 'Church Street', 'Station Road', 'Queen Street', 'Mill Road']

    # campus with the min and max budget students there usually have per week in £
    campuses = [
        {"campus": "Belfast", "min_budget": 100, "max_budget": 200},
        {"campus": "Coleraine", "min_budget": 80, "max_budget": 160},
        {"campus": "Derry~Londonderry", "min_budget": 80, "max_budget": 150},
    ]

    # possible courses
    courses = ['Computing', 'Computer Science', 'Software Engineering', 'Business Studies', 'Nursing',
               'Psychology', 'Law', 'Accounting', 'Biomedical Science', 'Architecture', 'Marketing']

    # possible relation with guarantor and emergency contact
    relationships = ['Parent', 'Sibling', 'Guardian', 'Grandparent']

    # account status, active put more times so most accounts are active
    account_statuses = ['active', 'active', 'active', 'active', 'active', 'active', 'active', 'active', 'inactive', 'suspended']

    student_list = []   # space for student list

    # to create 125 students
    for i in range(125):
        # picking name, town, campus etc again for every new student
        first = random.choice(first_names)
        last = random.choice(last_names)
        town = random.choice(towns)
        campus = random.choice(campuses)
        year_of_study = random.randint(1, 4)

        # age between 18 and 30, then making a birthday from that age
        age = random.randint(18, 30)
        date_of_birth = datetime(today.year - age, random.randint(1, 12), random.randint(1, 28))

        # date when the account was made, sometime in the last 2 years
        joined_at = random_date(today - timedelta(days=730), today - timedelta(days=1))

        verified = random.choice([True, True, True, False])   # most students are verified

        # every student first verifies email when they sign up
        verification_history = [{
            "_id": new_id(),
            "date": mongo_date(joined_at),
            "check_type": "Email verification",
            "result": "Passed"
        }]
        # then student id check, passed only if student is verified
        verification_history.append({
            "_id": new_id(),
            "date": mongo_date(joined_at + timedelta(days=random.randint(1, 14))),
            "check_type": "Student ID check",
            "result": "Passed" if verified else "Failed"
        })

        # one or two emergency contacts
        emergency_contacts = []
        for c in range(random.randint(1, 2)):
            emergency_contacts.append({
                "_id": new_id(),
                "name": random.choice(first_names) + " " + last,
                "relationship": random.choice(relationships),
                "phone": make_phone()
            })

        # to insert student details as a dictionary into the list
        student_list.append({
            "student_id": "STU" + str(i + 1).zfill(3),   # STU001, STU002...
            "name": {
                "first_name": first,
                "last_name": last
            },
            # added the number so every email is different
            "email": first.lower() + "." + last.lower().replace("'", "") + str(i + 1) + "@example.com",
            "phone": make_phone(),
            "date_of_birth": mongo_date(date_of_birth),
            "home_address": {
                "street": str(random.randint(1, 200)) + " " + random.choice(streets),
                "city": town["city"],
                "postcode": random.choice(town["postcodes"]) + " " + str(random.randint(1, 9)) + random.choice("ABDEFGHJLNPQRSTUWXYZ") + random.choice("ABDEFGHJLNPQRSTUWXYZ")
            },
            "campus": campus["campus"],
            "course": random.choice(courses),
            "year_of_study": year_of_study,
            "max_budget_per_week": random.randint(campus["min_budget"], campus["max_budget"]),
            "guarantor": {
                "name": random.choice(first_names) + " " + last,
                "relationship": random.choice(relationships),
                "phone": make_phone()
            },
            "preferences": {
                "room_type": random.choice(['Single', 'Double', 'Studio']),
                "ensuite": random.choice([True, False]),
                "bills_included": random.choice([True, False])
            },
            "account_status": random.choice(account_statuses),
            "verified": verified,
            "joined_at": mongo_date(joined_at),
            "emergency_contacts": emergency_contacts,
            "previous_applications": [],          # empty for now, will add when making applications
            "verification_history": verification_history
        })

    return student_list


students = generate_data()  # calling function to run it

# saving the list into students.json file
with open('students.json', 'w', encoding="utf-8") as fout:
    json.dump(students, fout, indent=4)