from flask import Blueprint, request, make_response, jsonify
from bson import ObjectId
from datetime import datetime
import jwt
import config
from security import jwt_required, admin_required

# group for properties and their rooms and reviews
# (rooms and reviews are sub-documents inside a property)
property_routes = Blueprint("property_routes", __name__)


# GET all properties with pagination
# e.g. /api/v1.0/properties?pn=2&ps=10
@property_routes.route("/api/v1.0/properties", methods=["GET"])
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

        for prop in config.properties.find().skip(page_start).limit(page_size):
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
@property_routes.route("/api/v1.0/properties/<string:id>", methods=["GET"])
def getOneProperty(id):
    prop = config.properties.find_one({"property_id": id})

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
@property_routes.route("/api/v1.0/properties/search", methods=["GET"])
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

        for prop in config.properties.find(query).skip(page_start).limit(page_size):
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


# GET properties that have at least one available room
# optional move_in_date shows only rooms free by that date
# e.g. /api/v1.0/properties/available?move_in_date=2026-12-01
@property_routes.route("/api/v1.0/properties/available", methods=["GET"])
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

        for prop in config.properties.find({"rooms": {"$elemMatch": room_query}}).skip(page_start).limit(page_size):
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


# POST a new property
@property_routes.route("/api/v1.0/properties", methods=["POST"])
@jwt_required
@admin_required
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
    last_property = config.properties.find_one(sort=[("property_id", -1)])
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

    config.properties.insert_one(new_property)

    new_property_link = "http://127.0.0.1:5001/api/v1.0/properties/" + new_property_id
    return make_response(jsonify({"url": new_property_link}), 201)


# PUT update a property
# only the fields sent in form-data are changed
@property_routes.route("/api/v1.0/properties/<string:id>", methods=["PUT"])
@jwt_required
@admin_required
def editProperty(id):
    if config.properties.find_one({"property_id": id}) is None:
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

    config.properties.update_one({"property_id": id}, {"$set": updates})

    edited_property_link = "http://127.0.0.1:5001/api/v1.0/properties/" + id
    return make_response(jsonify({"url": edited_property_link}), 200)


# DELETE a property
# blocked if the property has any applications, so old records don't break
@property_routes.route("/api/v1.0/properties/<string:id>", methods=["DELETE"])
@jwt_required
@admin_required
def deleteProperty(id):
    if config.properties.find_one({"property_id": id}) is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # checking if any application points to this property
    if config.applications.find_one({"property_id": id}) is not None:
        return make_response(
            jsonify({"error": "Property has application history and cannot be deleted"}), 409
        )

    config.properties.delete_one({"property_id": id})

    return make_response(jsonify({}), 204)


# POST a new room into a property's rooms array
@property_routes.route("/api/v1.0/properties/<string:id>/rooms", methods=["POST"])
@jwt_required
@admin_required
def addRoom(id):
    prop = config.properties.find_one({"property_id": id})
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

    config.properties.update_one(
        {"property_id": id},
        {"$push": {"rooms": new_room}, "$set": {"recent_update": datetime.now()}}
    )

    return make_response(jsonify({"room_id": str(new_room["_id"]), "room_number": new_room["room_number"]}), 201)


# PUT update a room inside a property
# only the fields sent in form-data are changed
@property_routes.route("/api/v1.0/properties/<string:id>/rooms/<string:room_id>", methods=["PUT"])
@jwt_required
@admin_required
def editRoom(id, room_id):
    prop = config.properties.find_one({"property_id": id})
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
    config.properties.update_one(
        {"property_id": id},
        {"$set": {"rooms": prop["rooms"], "recent_update": datetime.now()}}
    )

    edited_room_link = "http://127.0.0.1:5001/api/v1.0/properties/" + id
    return make_response(jsonify({"url": edited_room_link}), 200)


# DELETE a room from a property
# blocked if any application uses this room, so old records don't break
@property_routes.route("/api/v1.0/properties/<string:id>/rooms/<string:room_id>", methods=["DELETE"])
@jwt_required
@admin_required
def deleteRoom(id, room_id):
    prop = config.properties.find_one({"property_id": id})
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
    if config.applications.find_one({"room_id": room_id}) is not None:
        return make_response(
            jsonify({"error": "Room has application history and cannot be deleted"}), 409
        )

    # $pull removes the room with this _id from the rooms array
    config.properties.update_one(
        {"property_id": id},
        {"$pull": {"rooms": {"_id": room["_id"]}}, "$set": {"recent_update": datetime.now()}}
    )

    return make_response(jsonify({}), 204)


# GET all reviews of a property
# e.g. /api/v1.0/properties/PRP001/reviews
@property_routes.route("/api/v1.0/properties/<string:id>/reviews", methods=["GET"])
def getReviews(id):
    prop = config.properties.find_one({"property_id": id})

    # if no property has this id
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    data_to_return = []

    for review in prop.get("reviews", []):
        review["_id"] = str(review["_id"])   # objectid into text for jsonify
        data_to_return.append(review)

    return make_response(jsonify(data_to_return), 200)


# POST a review for a property
# only a student with an accepted application at this property can review, once
@property_routes.route("/api/v1.0/properties/<string:id>/reviews", methods=["POST"])
@jwt_required
def addReview(id):
    # reading who is logged in from the token
    token = request.headers.get("x-access-token")
    data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

    # only students write reviews
    if data["role"] != "student":
        return make_response(jsonify({"error": "Only students can write reviews"}), 403)

    prop = config.properties.find_one({"property_id": id})
    if prop is None:
        return make_response(jsonify({"error": "Property not found"}), 404)

    # student_id is not sent any more, it comes from the token
    required_fields = ["overall", "cleanliness", "landlord", "location", "comment"]
    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    student_id = data["linked_id"]   # the logged in student

    if config.students.find_one({"student_id": student_id}) is None:
        return make_response(jsonify({"error": "Student not found"}), 404)

    # student must have lived there (accepted application)
    accepted = config.applications.find_one({
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
    config.properties.update_one({"property_id": id}, {"$push": {"reviews": new_review}})

    return make_response(jsonify({"review_id": str(new_review["_id"])}), 201)