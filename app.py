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


# opposite of mongo_date, reads {"$date": ...} from the json file back into python date
# so we can compare dates

def read_date(value):
    if value is None:
        return None
    return datetime.strptime(value["$date"], "%Y-%m-%dT%H:%M:%SZ")


# to make a new unique mongodb id

def new_id():
    return {"$oid": str(ObjectId())}


# student can only get a room if account is active and student id is verified
# (the flask api should check the same thing)

def is_eligible(student):
    return student["account_status"] == "active" and student["verified"]


# working out the costs for a room and tenancy length
# weeks = months changed into weeks (6 -> 26, 9 -> 39, 12 -> 52)
# deposit = 4 weeks rent

def make_costs(room, tenancy_months, bills_included):
    weeks = round(tenancy_months * 52 / 12)
    rent = room["rent_per_week"]
    total_rent = rent * weeks
    deposit = rent * 4
    return {
        "rent_per_week": rent,
        "weeks": weeks,
        "total_rent": total_rent,
        "deposit": deposit,
        "bills_included": bills_included,
        "total_due": total_rent + deposit
    }


def generate_data(properties, students):

    today = datetime(2026, 10, 26)   # same fixed date as the other scripts

    # tenancy length in months, 12 put twice so it comes more often
    tenancy_lengths = [6, 9, 12, 12]

    # documents a student can upload with the application
    document_options = ["Student ID", "Proof of enrolment", "Guarantor form", "Bank statement"]

    # possible messages from student to landlord
    messages = ["Hi, I am interested in this room for the next academic year.",
                "Is the room still available? I would like to move in soon.",
                "I am a quiet student looking for a room close to campus.",
                "Can I move in with a friend who is also applying?",
                "I would like to apply for this room, please let me know."]

    # possible landlord notes
    accept_notes = ["All documents checked, happy to accept.", "Guarantor confirmed, room offered.",
                    "Good references, accepted."]
    reject_notes = ["Room already offered to another student.", "Documents were missing.",
                    "Guarantor could not be confirmed."]

    # possible review comments
    review_comments = ["Great location, only a short walk to campus.", "Landlord fixes things quickly.",
                       "Room is clean and quiet, good for studying.", "A bit expensive but the house is nice.",
                       "Heating was a problem in winter.", "Friendly housemates and good facilities."]

    application_list = []   # space for application list, each item is (submitted date, application)
    used_pairs = []         # student and room pairs already used, so no student applies twice for same room

    # students who can actually be accepted, mixed up so random students get rooms
    eligible_students = [s for s in students if is_eligible(s)]
    random.shuffle(eligible_students)

    # active students, they can make pending, rejected or withdrawn applications
    active_students = [s for s in students if s["account_status"] == "active"]


    # ---------- part 1: accepted applications for let and reserved rooms ----------
    # every let or reserved room needs one accepted application

    for prop in properties:
        for room in prop["rooms"]:
            if room["room_status"] not in ["let", "reserved"]:
                continue

            # if no eligible student is left, the room becomes available again
            if len(eligible_students) == 0:
                room["room_status"] = "available"
                room["available_from"] = mongo_date(random_date(today, today + timedelta(days=90)))
                continue

            student = eligible_students.pop()   # each eligible student gets only one room

            if room["room_status"] == "let":
                # let = student already moved in at start of the term
                move_in = random_date(datetime(2026, 8, 15), datetime(2026, 10, 1))
                submitted = move_in - timedelta(days=random.randint(30, 90))
            else:
                # reserved = accepted but student moves in later
                move_in = random_date(today + timedelta(days=7), today + timedelta(days=90))
                submitted = random_date(today - timedelta(days=30), today - timedelta(days=2))

            decided = min(submitted + timedelta(days=random.randint(1, 7)), today)

            application = make_application(student, prop, room, "accepted", submitted, decided,
                                           move_in, random.choice(tenancy_lengths), messages,
                                           document_options, accept_notes, reject_notes)
            application_list.append((submitted, application))
            used_pairs.append((student["student_id"], room["_id"]["$oid"]))

            # half of the students who already moved in leave a review
            if room["room_status"] == "let" and random.random() < 0.5:
                prop["reviews"].append({
                    "_id": new_id(),
                    "student_id": student["student_id"],
                    "ratings": {
                        "overall": random.randint(2, 5),
                        "cleanliness": random.randint(1, 5),
                        "landlord": random.randint(1, 5),
                        "location": random.randint(2, 5)
                    },
                    "comment": random.choice(review_comments),
                    "date": mongo_date(random_date(move_in + timedelta(days=14), today))
                })


    # ---------- part 2: pending, rejected and withdrawn applications ----------
    # keep adding until we have 350 applications in total

    while len(application_list) < 350:
        prop = random.choice(properties)
        room = random.choice(prop["rooms"])
        student = random.choice(active_students)

        # skip if this student already applied for this room
        if (student["student_id"], room["_id"]["$oid"]) in used_pairs:
            continue

        if room["room_status"] == "available":
            # available room can have new pending ones, or ones the student withdrew
            status = random.choice(["pending", "pending", "withdrawn"])
        else:
            # room is taken, so older applications were rejected or withdrawn
            status = random.choice(["rejected", "withdrawn"])

        if status == "pending":
            submitted = random_date(today - timedelta(days=14), today - timedelta(hours=1))
            available_from = read_date(room["available_from"])
            move_in = random_date(available_from, available_from + timedelta(days=30))   # not before room is free
            decided = None
        else:
            submitted = random_date(today - timedelta(days=180), today - timedelta(days=2))
            decided = min(submitted + timedelta(days=random.randint(1, 10)), today)
            move_in = random_date(submitted + timedelta(days=14), submitted + timedelta(days=120))

        application = make_application(student, prop, room, status, submitted, decided,
                                       move_in, random.choice(tenancy_lengths), messages,
                                       document_options, accept_notes, reject_notes)
        application_list.append((submitted, application))
        used_pairs.append((student["student_id"], room["_id"]["$oid"]))


    # ---------- part 3: sort by date and give ids ----------
    # oldest application gets APP001

    application_list.sort(key=lambda item: item[0])

    # quick way to find a student by id
    students_by_id = {}
    for s in students:
        students_by_id[s["student_id"]] = s

    final_list = []
    for number, item in enumerate(application_list):
        application = item[1]
        application_id = "APP" + str(number + 1).zfill(3)
        # putting application_id at the top of the dictionary
        final_list.append({"application_id": application_id, **application})

        # adding this application to the student's previous applications
        students_by_id[application["student_id"]]["previous_applications"].append(application_id)

    return final_list


# builds one application dictionary

def make_application(student, prop, room, status, submitted, decided, move_in, tenancy_months,
                     messages, document_options, accept_notes, reject_notes):

    costs = make_costs(room, tenancy_months, prop["bills_included"])
    move_out = move_in + timedelta(days=costs["weeks"] * 7)

    # every application starts as pending, then changes if decided
    status_history = [{
        "_id": new_id(),
        "status": "pending",
        "date": mongo_date(submitted),
        "changed_by": "student"
    }]
    if status != "pending":
        status_history.append({
            "_id": new_id(),
            "status": status,
            "date": mongo_date(decided),
            # landlord accepts or rejects, student withdraws
            "changed_by": "student" if status == "withdrawn" else "landlord"
        })

    # deposit is paid only after the application is accepted
    deposit_payments = []
    if status == "accepted":
        paid_at = min(decided + timedelta(days=random.randint(1, 3)), datetime(2026, 10, 26))
        deposit_payments.append({
            "_id": new_id(),
            "amount": costs["deposit"],
            "paid_at": mongo_date(paid_at),
            "method": random.choice(["Card", "Bank transfer"])
        })

    # landlord leaves a note when accepting or rejecting
    landlord_notes = []
    if status == "accepted":
        landlord_notes.append({"_id": new_id(), "note": random.choice(accept_notes), "date": mongo_date(decided)})
    elif status == "rejected":
        landlord_notes.append({"_id": new_id(), "note": random.choice(reject_notes), "date": mongo_date(decided)})

    # guarantor is always confirmed for accepted, random for others
    guarantor_confirmed = True if status == "accepted" else random.choice([True, False])

    return {
        "student_id": student["student_id"],
        "property_id": prop["property_id"],
        "room_id": room["_id"]["$oid"],
        "application_status": status,
        "message": random.choice(messages),
        "submitted_at": mongo_date(submitted),
        "decided_at": mongo_date(decided) if decided else None,
        "tenancy_period": {
            "move_in_date": mongo_date(move_in),
            "move_out_date": mongo_date(move_out),
            "tenancy_months": tenancy_months
        },
        "guarantor_confirmation": {
            "confirmed": guarantor_confirmed,
            "confirmed_at": mongo_date(submitted + timedelta(days=1)) if guarantor_confirmed else None
        },
        "costs": costs,
        "status_history": status_history,
        "deposit_payments": deposit_payments,
        "documents_submitted": random.sample(document_options, random.randint(1, 4)),
        "landlord_notes": landlord_notes
    }


# loading the properties and students we made before
with open('properties.json', 'r', encoding="utf-8") as fin:
    properties = json.load(fin)

with open('students.json', 'r', encoding="utf-8") as fin:
    students = json.load(fin)

applications = generate_data(properties, students)  # calling function to run it

# saving applications, and saving properties and students again
# because rooms, reviews and previous_applications were changed
with open('applications.json', 'w', encoding="utf-8") as fout:
    json.dump(applications, fout, indent=4)

with open('properties.json', 'w', encoding="utf-8") as fout:
    json.dump(properties, fout, indent=4)

with open('students.json', 'w', encoding="utf-8") as fout:
    json.dump(students, fout, indent=4)