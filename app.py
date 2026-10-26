from flask import Flask, make_response, jsonify, request
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta, timezone
import jwt
import bcrypt  
from functools import wraps 

app = Flask(__name__)
app.config["SECRET_KEY"] = "safsecretkey"   # used to sign and check tokens

# connecting to mongodb and the student accommodation database
client = MongoClient("mongodb://localhost:27017/")
db = client.safDB
properties = db.property
students = db.student
applications = db.application
users = db.user
blacklist = db.blacklist   # tokens of users who logged out


# checks that a valid token is sent in the x-access-token header
def jwt_required(func):
    @wraps(func)
    def jwt_required_wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")

        if not token:
            return make_response(jsonify({"error": "Token is missing"}), 401)

        try:
            jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.InvalidTokenError:     # wrong, changed or expired token
            return make_response(jsonify({"error": "Token is invalid or expired"}), 401)

        # token was cancelled by logout
        if blacklist.find_one({"token": token}) is not None:
            return make_response(jsonify({"error": "Token has been cancelled"}), 401)

        return func(*args, **kwargs)
    return jwt_required_wrapper


# checks that the logged in user is an admin
# always used under @jwt_required, so the token is already checked
def admin_required(func):
    @wraps(func)
    def admin_required_wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")
        data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])

        if data["role"] != "admin":
            return make_response(jsonify({"error": "Admin access required"}), 403)

        return func(*args, **kwargs)
    return admin_required_wrapper


@app.route("/", methods=["GET"])
def indexPage():
    return make_response("<h1>Student Accommodation Finder API is running</h1>", 200)


# LOGIN using Basic Auth (username + password in Postman's Authorization tab)
# returns a token that lasts 30 minutes
@app.route("/api/v1.0/login", methods=["GET"])
def login():
    auth = request.authorization

    if auth:
        user = users.find_one({"username": auth.username})

        if user is not None:
            # suspended or inactive accounts can't log in
            if not user["active"]:
                return make_response(jsonify({"error": "Account is not active"}), 403)

            # checking the typed password against the saved bcrypt hash
            if bcrypt.checkpw(auth.password.encode("utf-8"), user["password"].encode("utf-8")):
                token = jwt.encode({
                    "user": auth.username,
                    "role": user["role"],
                    "linked_id": user["linked_id"],     # student_id, or None for admin
                    "exp": datetime.now(timezone.utc) + timedelta(minutes=30)
                }, app.config["SECRET_KEY"], algorithm="HS256")

                return make_response(jsonify({"token": token}), 200)
            else:
                return make_response(jsonify({"error": "Bad password"}), 401)
        else:
            return make_response(jsonify({"error": "Bad username"}), 401)

    return make_response(jsonify({"error": "Authentication required"}), 401)


# GET all properties with pagination
# e.g. /api/v1.0/properties?pn=2&ps=10
@app.route("/api/v1.0/properties", methods=["GET"])
def getAllProperties():
    try:
        page_num = int(request.args.get("pn", 1))     # page number, 1 if not given
        page_size = int(request.args.get("ps", 5))    # how many on one page, 5 if not given

        if page_num < 1 or page_size < 1:
            return make_response(
                jsonify({"error": "Page number and page size must be positive"}), 400
            )

        page_start = page_size * (page_num - 1)   # how many to skip

        data_to_return = []

        for prop in properties.find().skip(page_start).limit(page_size):
            # ObjectId can't go into json, so changing every _id into text
            prop["_id"] = str(prop["_id"])

            for room in prop.get("rooms", []):
                room["_id"] = str(room["_id"])

            for review in prop.get("reviews", []):
                review["_id"] = str(review["_id"])

            data_to_return.append(prop)

        return make_response(jsonify(data_to_return), 200)

    except ValueError:
        return make_response(
            jsonify({"error": "Page number and page size must be integers"}), 400
        )

# GET one property using its property_id
# e.g. /api/v1.0/properties/PRP001
@app.route("/api/v1.0/properties/<string:id>", methods=["GET"])
def getOneProperty(id):
    prop = properties.find_one({"property_id": id})

    # if no property has this id
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # changing every _id into text so jsonify can handle it
    prop["_id"] = str(prop["_id"])

    for room in prop.get("rooms", []):
        room["_id"] = str(room["_id"])

    for review in prop.get("reviews", []):
        review["_id"] = str(review["_id"])

    return make_response(jsonify(prop), 200)

# SEARCH properties with filters and pagination
# e.g. /api/v1.0/properties/search?campus=Belfast&max_rent=120&ensuite=true
@app.route("/api/v1.0/properties/search", methods=["GET"])
def searchProperties():
    campus = request.args.get("campus")
    property_type = request.args.get("type")
    max_rent = request.args.get("max_rent")
    bills_included = request.args.get("bills_included")
    ensuite = request.args.get("ensuite")

    # at least one filter is needed
    if not campus and not property_type and not max_rent and not bills_included and not ensuite:
        return make_response(
            jsonify({"error": "Please provide at least one search filter"}), 400
        )

    try:
        page_num = int(request.args.get("pn", 1))
        page_size = int(request.args.get("ps", 5))

        if page_num < 1 or page_size < 1:
            return make_response(
                jsonify({"error": "Page number and page size must be positive"}), 400
            )

        page_start = page_size * (page_num - 1)

        # building the search one filter at a time
        query = {}

        if campus:
            query["nearest_campus"] = campus

        if property_type:
            query["property_type"] = property_type

        if bills_included:
            query["bills_included"] = bills_included.lower() == "true"   # text "true" -> True

        # rent and ensuite are inside the rooms array, so they must match the SAME room
        room_query = {}

        if max_rent:
            room_query["rent_per_week"] = {"$lte": int(max_rent)}   # less than or equal

        if ensuite:
            room_query["ensuite"] = ensuite.lower() == "true"

        if room_query:
            query["rooms"] = {"$elemMatch": room_query}

        data_to_return = []

        for prop in properties.find(query).skip(page_start).limit(page_size):
            prop["_id"] = str(prop["_id"])

            for room in prop.get("rooms", []):
                room["_id"] = str(room["_id"])

            for review in prop.get("reviews", []):
                review["_id"] = str(review["_id"])

            data_to_return.append(prop)

        return make_response(jsonify(data_to_return), 200)

    except ValueError:
        return make_response(
            jsonify({"error": "Page number, page size and max rent must be numbers"}), 400
        )


# POST a new property
@app.route("/api/v1.0/properties", methods=["POST"])
def addProperty():
    # fields that must be sent
    required_fields = ["title", "property_type", "street", "city", "postcode", "nearest_campus",
                       "distance_to_campus_km", "landlord_name", "landlord_email",
                       "landlord_phone", "bills_included"]

    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    # only allowed values for type and campus
    if request.form["property_type"] not in ["House share", "Studio", "Apartment", "Purpose-built halls"]:
        return make_response(jsonify({"error": "Invalid property type"}), 400)

    if request.form["nearest_campus"] not in ["Belfast", "Coleraine", "Derry~Londonderry"]:
        return make_response(jsonify({"error": "Invalid campus"}), 400)

    try:
        distance = float(request.form["distance_to_campus_km"])
    except ValueError:
        return make_response(jsonify({"error": "Distance must be a number"}), 400)

    # making the next id, e.g. last is PRP125 -> new one is PRP126
    last_property = properties.find_one(sort=[("property_id", -1)])
    if last_property:
        next_number = int(last_property["property_id"][3:]) + 1
    else:
        next_number = 1
    new_property_id = "PRP" + str(next_number).zfill(3)

    # amenities come as text like "WiFi,Parking", so splitting into a list
    amenities = []
    if request.form.get("amenities"):
        amenities = [a.strip() for a in request.form["amenities"].split(",")]

    new_property = {
        "property_id": new_property_id,
        "title": request.form["title"],
        "property_type": request.form["property_type"],
        "address": {
            "street": request.form["street"],
            "city": request.form["city"],
            "postcode": request.form["postcode"]
        },
        "nearest_campus": request.form["nearest_campus"],
        "distance_to_campus_km": distance,
        "landlord": {
            "name": request.form["landlord_name"],
            "email": request.form["landlord_email"],
            "phone": request.form["landlord_phone"]
        },
        "bills_included": request.form["bills_included"].lower() == "true",
        "amenities": amenities,
        "rooms": [],          # rooms are added later with the rooms endpoint
        "reviews": [],
        "recent_update": datetime.now()
    }

    properties.insert_one(new_property)

    new_property_link = "http://127.0.0.1:5001/api/v1.0/properties/" + new_property_id
    return make_response(jsonify({"url": new_property_link}), 201)


# PUT update a property
# only the fields sent in form-data are changed
@app.route("/api/v1.0/properties/<string:id>", methods=["PUT"])
def editProperty(id):
    if properties.find_one({"property_id": id}) is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # form field name -> where it is saved in mongodb
    allowed_fields = {
        "title": "title",
        "property_type": "property_type",
        "street": "address.street",
        "city": "address.city",
        "postcode": "address.postcode",
        "nearest_campus": "nearest_campus",
        "distance_to_campus_km": "distance_to_campus_km",
        "landlord_name": "landlord.name",
        "landlord_email": "landlord.email",
        "landlord_phone": "landlord.phone",
        "bills_included": "bills_included",
        "amenities": "amenities"
    }

    updates = {}

    for field in allowed_fields:
        if request.form.get(field):
            updates[allowed_fields[field]] = request.form[field]

    if not updates:
        return make_response(jsonify({"error": "No fields to update"}), 400)

    # same checks as POST, but only if that field was sent
    if "property_type" in updates and updates["property_type"] not in ["House share", "Studio", "Apartment", "Purpose-built halls"]:
        return make_response(jsonify({"error": "Invalid property type"}), 400)

    if "nearest_campus" in updates and updates["nearest_campus"] not in ["Belfast", "Coleraine", "Derry~Londonderry"]:
        return make_response(jsonify({"error": "Invalid campus"}), 400)

    if "distance_to_campus_km" in updates:
        try:
            updates["distance_to_campus_km"] = float(updates["distance_to_campus_km"])
        except ValueError:
            return make_response(jsonify({"error": "Distance must be a number"}), 400)

    if "bills_included" in updates:
        updates["bills_included"] = updates["bills_included"].lower() == "true"

    if "amenities" in updates:
        updates["amenities"] = [a.strip() for a in updates["amenities"].split(",")]

    updates["recent_update"] = datetime.now()

    properties.update_one({"property_id": id}, {"$set": updates})

    edited_property_link = "http://127.0.0.1:5001/api/v1.0/properties/" + id
    return make_response(jsonify({"url": edited_property_link}), 200)

# DELETE a property
# blocked if the property has any applications, so old records don't break
@app.route("/api/v1.0/properties/<string:id>", methods=["DELETE"])
def deleteProperty(id):
    if properties.find_one({"property_id": id}) is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # checking if any application points to this property
    if applications.find_one({"property_id": id}) is not None:
        return make_response(
            jsonify({"error": "Property has application history and cannot be deleted"}), 409
        )

    properties.delete_one({"property_id": id})

    return make_response(jsonify({}), 204)

# GET properties that have at least one available room
# optional move_in_date shows only rooms free by that date
# e.g. /api/v1.0/properties/available?move_in_date=2026-12-01
@app.route("/api/v1.0/properties/available", methods=["GET"])
def getAvailableProperties():
    move_in = request.args.get("move_in_date")

    try:
        page_num = int(request.args.get("pn", 1))
        page_size = int(request.args.get("ps", 5))

        if page_num < 1 or page_size < 1:
            return make_response(
                jsonify({"error": "Page number and page size must be positive"}), 400
            )

        page_start = page_size * (page_num - 1)

        # without a date: any available room
        room_query = {"room_status": "available"}

        # with a date: the room must be free on or before that date
        if move_in:
            move_in_date = datetime.strptime(move_in, "%Y-%m-%d")   # text -> python date
            room_query["available_from"] = {"$lte": move_in_date}

        data_to_return = []

        for prop in properties.find({"rooms": {"$elemMatch": room_query}}).skip(page_start).limit(page_size):
            prop["_id"] = str(prop["_id"])

            # only keeping the rooms the student can actually get
            available_rooms = []
            for room in prop.get("rooms", []):
                if room["room_status"] == "available":
                    if not move_in or room["available_from"] <= move_in_date:
                        room["_id"] = str(room["_id"])
                        available_rooms.append(room)
            prop["rooms"] = available_rooms

            for review in prop.get("reviews", []):
                review["_id"] = str(review["_id"])

            data_to_return.append(prop)

        return make_response(jsonify(data_to_return), 200)

    except ValueError:
        return make_response(
            jsonify({"error": "Page values must be integers and date must be YYYY-MM-DD"}), 400
        )
# POST a review for a property
# only a student with an accepted application at this property can review, once
@app.route("/api/v1.0/properties/<string:id>/reviews", methods=["POST"])
def addReview(id):
    prop = properties.find_one({"property_id": id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    required_fields = ["student_id", "overall", "cleanliness", "landlord", "location", "comment"]
    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    student_id = request.form["student_id"]

    if students.find_one({"student_id": student_id}) is None:
        return make_response(jsonify({"error": "Student not found"}), 404)

    # student must have lived there (accepted application)
    accepted = applications.find_one({
        "student_id": student_id,
        "property_id": id,
        "application_status": "accepted"
    })
    if accepted is None:
        return make_response(
            jsonify({"error": "Only students accepted at this property can review it"}), 403
        )

    # one review per student per property
    for review in prop.get("reviews", []):
        if review["student_id"] == student_id:
            return make_response(jsonify({"error": "Student has already reviewed this property"}), 409)

    # ratings must be whole numbers from 1 to 5
    ratings = {}
    try:
        for rating in ["overall", "cleanliness", "landlord", "location"]:
            value = int(request.form[rating])
            if value < 1 or value > 5:
                return make_response(jsonify({"error": rating + " must be between 1 and 5"}), 400)
            ratings[rating] = value
    except ValueError:
        return make_response(jsonify({"error": "Ratings must be whole numbers"}), 400)

    new_review = {
        "_id": ObjectId(),
        "student_id": student_id,
        "ratings": ratings,
        "comment": request.form["comment"],
        "date": datetime.now()
    }

    # $push adds the review to the end of the reviews array
    properties.update_one({"property_id": id}, {"$push": {"reviews": new_review}})

    return make_response(jsonify({"review_id": str(new_review["_id"])}), 201)

# POST a new room into a property's rooms array
@app.route("/api/v1.0/properties/<string:id>/rooms", methods=["POST"])
def addRoom(id):
    prop = properties.find_one({"property_id": id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    required_fields = ["room_type", "rent_per_week", "ensuite"]
    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    if request.form["room_type"] not in ["Single", "Double", "Studio"]:
        return make_response(jsonify({"error": "Room type must be Single, Double or Studio"}), 400)

    try:
        rent = int(request.form["rent_per_week"])

        # available from the given date, or from today if no date is sent
        if request.form.get("available_from"):
            available_from = datetime.strptime(request.form["available_from"], "%Y-%m-%d")
        else:
            available_from = datetime.now()
    except ValueError:
        return make_response(
            jsonify({"error": "Rent must be a number and available_from must be YYYY-MM-DD"}), 400
        )

    if rent <= 0:
        return make_response(jsonify({"error": "Rent must be more than 0"}), 400)

    # next room number, e.g. last is R4 -> new one is R5
    highest = 0
    for room in prop.get("rooms", []):
        number = int(room["room_number"][1:])     # "R4" -> 4
        if number > highest:
            highest = number

    new_room = {
        "_id": ObjectId(),
        "room_number": "R" + str(highest + 1),
        "room_type": request.form["room_type"],
        "rent_per_week": rent,
        "ensuite": request.form["ensuite"].lower() == "true",
        "room_status": "available",           # a new room is always free
        "available_from": available_from
    }

    properties.update_one(
        {"property_id": id},
        {"$push": {"rooms": new_room}, "$set": {"recent_update": datetime.now()}}
    )

    return make_response(jsonify({"room_id": str(new_room["_id"]), "room_number": new_room["room_number"]}), 201)

# PUT update a room inside a property
# only the fields sent in form-data are changed
@app.route("/api/v1.0/properties/<string:id>/rooms/<string:room_id>", methods=["PUT"])
def editRoom(id, room_id):
    prop = properties.find_one({"property_id": id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # finding the room inside the rooms array
    room = None
    for r in prop.get("rooms", []):
        if str(r["_id"]) == room_id:
            room = r
    if room is None:
        return make_response(jsonify({"error": "Room not found in this property"}), 404)

    changed = False

    if request.form.get("room_type"):
        if request.form["room_type"] not in ["Single", "Double", "Studio"]:
            return make_response(jsonify({"error": "Room type must be Single, Double or Studio"}), 400)
        room["room_type"] = request.form["room_type"]
        changed = True

    try:
        if request.form.get("rent_per_week"):
            rent = int(request.form["rent_per_week"])
            if rent <= 0:
                return make_response(jsonify({"error": "Rent must be more than 0"}), 400)
            room["rent_per_week"] = rent
            changed = True

        # only a free room can have its available date changed
        if request.form.get("available_from"):
            if room["room_status"] != "available":
                return make_response(jsonify({"error": "Only available rooms can change available_from"}), 409)
            room["available_from"] = datetime.strptime(request.form["available_from"], "%Y-%m-%d")
            changed = True
    except ValueError:
        return make_response(
            jsonify({"error": "Rent must be a number and available_from must be YYYY-MM-DD"}), 400
        )

    if request.form.get("ensuite"):
        room["ensuite"] = request.form["ensuite"].lower() == "true"
        changed = True

    if not changed:
        return make_response(jsonify({"error": "No fields to update"}), 400)

    # saving the whole rooms array back with the changed room in it
    properties.update_one(
        {"property_id": id},
        {"$set": {"rooms": prop["rooms"], "recent_update": datetime.now()}}
    )

    edited_room_link = "http://127.0.0.1:5001/api/v1.0/properties/" + id
    return make_response(jsonify({"url": edited_room_link}), 200)

# DELETE a room from a property
# blocked if any application uses this room, so old records don't break
@app.route("/api/v1.0/properties/<string:id>/rooms/<string:room_id>", methods=["DELETE"])
def deleteRoom(id, room_id):
    prop = properties.find_one({"property_id": id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # finding the room inside the rooms array
    room = None
    for r in prop.get("rooms", []):
        if str(r["_id"]) == room_id:
            room = r
    if room is None:
        return make_response(jsonify({"error": "Room not found in this property"}), 404)

    # checking if any application points to this room
    if applications.find_one({"room_id": room_id}) is not None:
        return make_response(
            jsonify({"error": "Room has application history and cannot be deleted"}), 409
        )

    # $pull removes the room with this _id from the rooms array
    properties.update_one(
        {"property_id": id},
        {"$pull": {"rooms": {"_id": room["_id"]}}, "$set": {"recent_update": datetime.now()}}
    )

    return make_response(jsonify({}), 204)

# POST a new application (student applies for a room)
@app.route("/api/v1.0/applications", methods=["POST"])
def addApplication():
    required_fields = ["student_id", "property_id", "room_id", "move_in_date", "tenancy_months"]
    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    student_id = request.form["student_id"]
    property_id = request.form["property_id"]
    room_id = request.form["room_id"]

    # ---- checking the student ----
    student = students.find_one({"student_id": student_id})
    if student is None:
        return make_response(jsonify({"error": "Student not found"}), 404)

    if student["account_status"] != "active" or not student["verified"]:
        return make_response(
            jsonify({"error": "Student account must be active and verified to apply"}), 403
        )

    # ---- checking the property and room ----
    prop = properties.find_one({"property_id": property_id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # finding the room inside the property's rooms array
    room = None
    for r in prop.get("rooms", []):
        if str(r["_id"]) == room_id:
            room = r
    if room is None:
        return make_response(jsonify({"error": "Room not found in this property"}), 404)

    if room["room_status"] != "available":
        return make_response(jsonify({"error": "Room is not available"}), 409)

    # ---- checking dates and tenancy length ----
    try:
        move_in = datetime.strptime(request.form["move_in_date"], "%Y-%m-%d")
        tenancy_months = int(request.form["tenancy_months"])
    except ValueError:
        return make_response(
            jsonify({"error": "move_in_date must be YYYY-MM-DD and tenancy_months a number"}), 400
        )

    if tenancy_months not in [6, 9, 12]:
        return make_response(jsonify({"error": "Tenancy must be 6, 9 or 12 months"}), 400)

    if move_in <= datetime.now():
        return make_response(jsonify({"error": "Move-in date must be in the future"}), 400)

    if room["available_from"] is not None and move_in < room["available_from"]:
        return make_response(jsonify({"error": "Room is not free until " + room["available_from"].strftime("%Y-%m-%d")}), 400)

    # ---- no second pending application for the same room ----
    duplicate = applications.find_one({
        "student_id": student_id,
        "room_id": room_id,
        "application_status": "pending"
    })
    if duplicate is not None:
        return make_response(jsonify({"error": "Student already has a pending application for this room"}), 409)

    # ---- working out the costs (same rules as the data generator) ----
    weeks = round(tenancy_months * 52 / 12)
    rent = room["rent_per_week"]
    total_rent = rent * weeks
    deposit = rent * 4

    # next id, e.g. APP125 -> APP126
    last_application = applications.find_one(sort=[("application_id", -1)])
    if last_application:
        next_number = int(last_application["application_id"][3:]) + 1
    else:
        next_number = 1
    new_application_id = "APP" + str(next_number).zfill(3)

    # documents come as text like "Student ID,Guarantor form"
    documents = []
    if request.form.get("documents_submitted"):
        documents = [d.strip() for d in request.form["documents_submitted"].split(",")]

    now = datetime.now()

    new_application = {
        "application_id": new_application_id,
        "student_id": student_id,
        "property_id": property_id,
        "room_id": room_id,
        "application_status": "pending",
        "message": request.form.get("message", ""),
        "submitted_at": now,
        "decided_at": None,
        "tenancy_period": {
            "move_in_date": move_in,
            "move_out_date": move_in + timedelta(days=weeks * 7),
            "tenancy_months": tenancy_months
        },
        "guarantor_confirmation": {
            "confirmed": False,
            "confirmed_at": None
        },
        "costs": {
            "rent_per_week": rent,
            "weeks": weeks,
            "total_rent": total_rent,
            "deposit": deposit,
            "bills_included": prop["bills_included"],
            "total_due": total_rent + deposit
        },
        "status_history": [{
            "_id": ObjectId(),
            "status": "pending",
            "date": now,
            "changed_by": "student"
        }],
        "deposit_payments": [],
        "documents_submitted": documents,
        "landlord_notes": []
    }

    applications.insert_one(new_application)

    # adding the new id to the student's previous applications
    students.update_one({"student_id": student_id}, {"$push": {"previous_applications": new_application_id}})

    new_application_link = "http://127.0.0.1:5001/api/v1.0/applications/" + new_application_id
    return make_response(jsonify({"url": new_application_link, "total_due": total_rent + deposit}), 201)

# GET all applications with pagination
# optional status filter, e.g. /api/v1.0/applications?status=pending
@app.route("/api/v1.0/applications", methods=["GET"])
def getAllApplications():
    status = request.args.get("status")

    if status and status not in ["pending", "accepted", "rejected", "withdrawn"]:
        return make_response(jsonify({"error": "Invalid status"}), 400)

    try:
        page_num = int(request.args.get("pn", 1))
        page_size = int(request.args.get("ps", 5))

        if page_num < 1 or page_size < 1:
            return make_response(
                jsonify({"error": "Page number and page size must be positive"}), 400
            )

        page_start = page_size * (page_num - 1)

        # empty query = all applications, or only the given status
        query = {}
        if status:
            query["application_status"] = status

        data_to_return = []

        for application in applications.find(query).skip(page_start).limit(page_size):
            application["_id"] = str(application["_id"])

            # changing the _id inside each array into text
            for history in application.get("status_history", []):
                history["_id"] = str(history["_id"])

            for payment in application.get("deposit_payments", []):
                payment["_id"] = str(payment["_id"])

            for note in application.get("landlord_notes", []):
                note["_id"] = str(note["_id"])

            data_to_return.append(application)

        return make_response(jsonify(data_to_return), 200)

    except ValueError:
        return make_response(
            jsonify({"error": "Page number and page size must be integers"}), 400
        )


# GET one application using its application_id
# e.g. /api/v1.0/applications/APP001
@app.route("/api/v1.0/applications/<string:id>", methods=["GET"])
def getOneApplication(id):
    application = applications.find_one({"application_id": id})

    # if no application has this id
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    # changing every _id into text so jsonify can handle it
    application["_id"] = str(application["_id"])

    for history in application.get("status_history", []):
        history["_id"] = str(history["_id"])

    for payment in application.get("deposit_payments", []):
        payment["_id"] = str(payment["_id"])

    for note in application.get("landlord_notes", []):
        note["_id"] = str(note["_id"])

    return make_response(jsonify(application), 200)


# PUT update an application
# - change details (move_in_date, tenancy_months, message) while it is pending
# - or change status: accepted / rejected (landlord) or withdrawn (student)
@app.route("/api/v1.0/applications/<string:id>", methods=["PUT"])
def editApplication(id):
    application = applications.find_one({"application_id": id})
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    # once decided, an application can't be changed any more
    if application["application_status"] != "pending":
        return make_response(jsonify({"error": "Only pending applications can be changed"}), 409)

    new_status = request.form.get("status")
    if new_status and new_status not in ["accepted", "rejected", "withdrawn"]:
        return make_response(jsonify({"error": "Status must be accepted, rejected or withdrawn"}), 400)

    # finding the property and the room this application is for
    prop = properties.find_one({"property_id": application["property_id"]})
    room = None
    for r in prop["rooms"]:
        if str(r["_id"]) == application["room_id"]:
            room = r

    updates = {}   # fields to $set
    pushes = {}    # items to $push into arrays
    now = datetime.now()

    # ---------- part 1: changing details ----------
    move_in = application["tenancy_period"]["move_in_date"]
    tenancy_months = application["tenancy_period"]["tenancy_months"]

    try:
        if request.form.get("move_in_date"):
            move_in = datetime.strptime(request.form["move_in_date"], "%Y-%m-%d")
            if move_in <= now:
                return make_response(jsonify({"error": "Move-in date must be in the future"}), 400)
            if room["available_from"] is not None and move_in < room["available_from"]:
                return make_response(jsonify({"error": "Room is not free until " + room["available_from"].strftime("%Y-%m-%d")}), 400)

        if request.form.get("tenancy_months"):
            tenancy_months = int(request.form["tenancy_months"])
            if tenancy_months not in [6, 9, 12]:
                return make_response(jsonify({"error": "Tenancy must be 6, 9 or 12 months"}), 400)
    except ValueError:
        return make_response(
            jsonify({"error": "move_in_date must be YYYY-MM-DD and tenancy_months a number"}), 400
        )

    # if dates or length changed, work out tenancy and costs again
    if request.form.get("move_in_date") or request.form.get("tenancy_months"):
        weeks = round(tenancy_months * 52 / 12)
        rent = application["costs"]["rent_per_week"]
        updates["tenancy_period"] = {
            "move_in_date": move_in,
            "move_out_date": move_in + timedelta(days=weeks * 7),
            "tenancy_months": tenancy_months
        }
        updates["costs.weeks"] = weeks
        updates["costs.total_rent"] = rent * weeks
        updates["costs.total_due"] = rent * weeks + application["costs"]["deposit"]

    if request.form.get("message"):
        updates["message"] = request.form["message"]

    # ---------- part 2: changing status ----------
    if new_status:
        if new_status == "accepted":
            # the room must still be free
            if room["room_status"] != "available":
                return make_response(jsonify({"error": "Room is no longer available"}), 409)

            # a student can only have one accepted room
            if applications.find_one({"student_id": application["student_id"], "application_status": "accepted"}):
                return make_response(jsonify({"error": "Student already has an accepted application"}), 409)

            # room becomes reserved (moving in later) and has no available date now
            room["room_status"] = "reserved"
            room["available_from"] = None
            properties.update_one({"property_id": prop["property_id"]}, {"$set": {"rooms": prop["rooms"]}})

            # every other pending application for this room is rejected
            applications.update_many(
                {"room_id": application["room_id"], "application_status": "pending", "application_id": {"$ne": id}},
                {"$set": {"application_status": "rejected", "decided_at": now},
                 "$push": {"status_history": {"_id": ObjectId(), "status": "rejected", "date": now, "changed_by": "landlord"},
                           "landlord_notes": {"_id": ObjectId(), "note": "Room already offered to another student.", "date": now}}}
            )

        updates["application_status"] = new_status
        updates["decided_at"] = now

        pushes["status_history"] = {
            "_id": ObjectId(),
            "status": new_status,
            "date": now,
            "changed_by": "student" if new_status == "withdrawn" else "landlord"
        }

        # landlord can add a note when accepting or rejecting
        if request.form.get("note") and new_status in ["accepted", "rejected"]:
            pushes["landlord_notes"] = {"_id": ObjectId(), "note": request.form["note"], "date": now}

    if not updates:
        return make_response(jsonify({"error": "No fields to update"}), 400)

    if pushes:
        applications.update_one({"application_id": id}, {"$set": updates, "$push": pushes})
    else:
        applications.update_one({"application_id": id}, {"$set": updates})

    edited_application_link = "http://127.0.0.1:5001/api/v1.0/applications/" + id
    return make_response(jsonify({"url": edited_application_link}), 200)

# DELETE an application
# only rejected or withdrawn ones, so active or accepted records are kept
@app.route("/api/v1.0/applications/<string:id>", methods=["DELETE"])
def deleteApplication(id):
    application = applications.find_one({"application_id": id})
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    if application["application_status"] not in ["rejected", "withdrawn"]:
        return make_response(
            jsonify({"error": "Only rejected or withdrawn applications can be deleted"}), 409
        )

    applications.delete_one({"application_id": id})

    # removing the id from the student's previous applications too
    students.update_one(
        {"student_id": application["student_id"]},
        {"$pull": {"previous_applications": id}}
    )

    return make_response(jsonify({}), 204)

# GET analytics: average rent per campus and room demand
# uses mongodb aggregation pipelines
@app.route("/api/v1.0/accommodation/analytics", methods=["GET"])
def getAnalytics():

    # 1. rent and rooms per campus
    rent_by_campus = []
    pipeline = [
        {"$unwind": "$rooms"},                       # one document per room
        {"$group": {
            "_id": "$nearest_campus",                # group rooms by campus
            "average_rent": {"$avg": "$rooms.rent_per_week"},
            "lowest_rent": {"$min": "$rooms.rent_per_week"},
            "highest_rent": {"$max": "$rooms.rent_per_week"},
            "total_rooms": {"$sum": 1},
            # adds 1 only when the room is available, otherwise 0
            "available_rooms": {"$sum": {"$cond": [{"$eq": ["$rooms.room_status", "available"]}, 1, 0]}}
        }},
        {"$sort": {"_id": 1}}                        # campus names A to Z
    ]
    for result in properties.aggregate(pipeline):
        rent_by_campus.append({
            "campus": result["_id"],
            "average_rent": round(result["average_rent"], 2),
            "lowest_rent": result["lowest_rent"],
            "highest_rent": result["highest_rent"],
            "total_rooms": result["total_rooms"],
            "available_rooms": result["available_rooms"]
        })

    # 2. how many applications in each status
    applications_by_status = []
    pipeline = [
        {"$group": {"_id": "$application_status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}                     # biggest first
    ]
    for result in applications.aggregate(pipeline):
        applications_by_status.append({"status": result["_id"], "count": result["count"]})

    # 3. top 5 properties with the most applications (room demand)
    most_wanted_properties = []
    pipeline = [
        {"$group": {"_id": "$property_id", "applications": {"$sum": 1}}},
        {"$sort": {"applications": -1}},
        {"$limit": 5}
    ]
    for result in applications.aggregate(pipeline):
        most_wanted_properties.append({"property_id": result["_id"], "applications": result["applications"]})

    return make_response(jsonify({
        "rent_by_campus": rent_by_campus,
        "applications_by_status": applications_by_status,
        "most_wanted_properties": most_wanted_properties
    }), 200)




if __name__ == "__main__":
    app.run(debug=True, port=5001)


