import random
import json
import bcrypt
from datetime import datetime, timedelta


# to get a random date and time between start and end date

def random_date(start, end):
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, seconds))


# changing python date into mongodb date format
# so it gets saved as a proper date in mongodb and not as a string

def mongo_date(d):
    return {"$date": d.strftime("%Y-%m-%dT%H:%M:%SZ")}


# hashing the password with bcrypt so the real password is never saved
# decode() changes it from bytes to text so it can go in the json file

def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def generate_data(students):

    today = datetime(2026, 10, 26)   # same fixed date as the other scripts

    user_list = []   # space for user list

    # admin accounts, all with the same test password
    admins = [
        {"username": "admin", "name": "System Admin", "email": "admin@example.com"},
        {"username": "accommodation.manager", "name": "Accommodation Manager", "email": "manager@example.com"},
    ]

    for admin in admins:
        user_list.append({
            "username": admin["username"],
            "password": hash_password("Admin123!"),
            "name": admin["name"],
            "email": admin["email"],
            "role": "admin",
            "linked_id": None,          # admin is not linked to a student
            "active": True,
            "created_at": mongo_date(datetime(2024, 9, 1))
        })

    # one login for each student, using their email as username
    # we want 125 users in total (2 admins + 123 students),
    # so 2 inactive students don't get a login (they never set up their account)
    skipped = 0
    for student in students:
        if student["account_status"] == "inactive" and skipped < 2:
            skipped = skipped + 1
            continue

        user_list.append({
            "username": student["email"],
            "password": hash_password("Password123!"),
            "name": student["name"]["first_name"] + " " + student["name"]["last_name"],
            "email": student["email"],
            "role": "student",
            "linked_id": student["student_id"],   # links login to the student record
            "active": student["account_status"] == "active",   # suspended or inactive cannot log in
            "created_at": student["joined_at"]
        })

    return user_list


# loading the students we made before
with open('students.json', 'r', encoding="utf-8") as fin:
    students = json.load(fin)

users = generate_data(students)  # calling function to run it

# saving the list into users.json file
with open('users.json', 'w', encoding="utf-8") as fout:
    json.dump(users, fout, indent=4)