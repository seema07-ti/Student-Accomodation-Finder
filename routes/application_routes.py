from flask import Blueprint, request, make_response, jsonify
from bson import ObjectId
from datetime import datetime, timedelta
import jwt
import config
from security import jwt_required, admin_required

# group for the application routes
application_routes = Blueprint("application_routes", __name__)


# POST a new application (student applies for a room)
@application_routes.route("/api/v1.0/applications", methods=["POST"])
@jwt_required
def addApplication():
    # reading who is logged in from the token
    token = request.headers.get("x-access-token")
    data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

    # only students apply for rooms
    if data["role"] != "student":
        return make_response(jsonify({"error": "Only students can apply for rooms"}), 403)

    # student_id is not sent any more, it comes from the token
    required_fields = ["property_id", "room_id", "move_in_date", "tenancy_months"]
    for field in required_fields:
        if not request.form.get(field):
            return make_response(jsonify({"error": "Missing field: " + field}), 400)

    student_id = data["linked_id"]   # the logged in student
    property_id = request.form["property_id"]
    room_id = request.form["room_id"]

    # ---- checking the student ----
    student = config.students.find_one({"student_id": student_id})
    if student is None:
        return make_response(jsonify({"error": "Student not found"}), 404)

    if student["account_status"] != "active" or not student["verified"]:
        return make_response(
            jsonify({"error": "Student account must be active and verified to apply"}), 403
        )

    # ---- checking the property and room ----
    prop = config.properties.find_one({"property_id": property_id})
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
    duplicate = config.applications.find_one({
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
    last_application = config.applications.find_one(sort=[("application_id", -1)])
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

    config.applications.insert_one(new_application)

    # adding the new id to the student's previous applications
    config.students.update_one({"student_id": student_id}, {"$push": {"previous_applications": new_application_id}})

    new_application_link = "http://127.0.0.1:5001/api/v1.0/applications/" + new_application_id
    return make_response(jsonify({"url": new_application_link, "total_due": total_rent + deposit}), 201)


# GET all applications with pagination
# optional status filter, e.g. /api/v1.0/applications?status=pending
@application_routes.route("/api/v1.0/applications", methods=["GET"])
@jwt_required
@admin_required
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

        for application in config.applications.find(query).skip(page_start).limit(page_size):
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
# a student can only see their own, an admin can see any
# e.g. /api/v1.0/applications/APP001
@application_routes.route("/api/v1.0/applications/<string:id>", methods=["GET"])
@jwt_required
def getOneApplication(id):
    application = config.applications.find_one({"application_id": id})

    # if no application has this id
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    # reading who is logged in from the token
    token = request.headers.get("x-access-token")
    data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

    # students can only see their own application
    if data["role"] != "admin" and application["student_id"] != data["linked_id"]:
        return make_response(jsonify({"error": "You can only view your own applications"}), 403)

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
# - student: change own details (move_in_date, tenancy_months, message) or withdraw
# - admin: accept or reject
@application_routes.route("/api/v1.0/applications/<string:id>", methods=["PUT"])
@jwt_required
def editApplication(id):
    application = config.applications.find_one({"application_id": id})
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    # reading who is logged in from the token
    token = request.headers.get("x-access-token")
    data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

    # students can only change their own application
    if data["role"] != "admin" and application["student_id"] != data["linked_id"]:
        return make_response(jsonify({"error": "You can only change your own applications"}), 403)

    # once decided, an application can't be changed any more
    if application["application_status"] != "pending":
        return make_response(jsonify({"error": "Only pending applications can be changed"}), 409)

    new_status = request.form.get("status")
    if new_status and new_status not in ["accepted", "rejected", "withdrawn"]:
        return make_response(jsonify({"error": "Status must be accepted, rejected or withdrawn"}), 400)

    # only admin accepts or rejects, only the student withdraws
    if new_status in ["accepted", "rejected"] and data["role"] != "admin":
        return make_response(jsonify({"error": "Only admin can accept or reject"}), 403)

    if new_status == "withdrawn" and data["role"] != "student":
        return make_response(jsonify({"error": "Only the student can withdraw"}), 403)

    # finding the property and the room this application is for
    prop = config.properties.find_one({"property_id": application["property_id"]})
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
            if config.applications.find_one({"student_id": application["student_id"], "application_status": "accepted"}):
                return make_response(jsonify({"error": "Student already has an accepted application"}), 409)

            # room becomes reserved (moving in later) and has no available date now
            room["room_status"] = "reserved"
            room["available_from"] = None
            config.properties.update_one({"property_id": prop["property_id"]}, {"$set": {"rooms": prop["rooms"]}})

            # every other pending application for this room is rejected
            config.applications.update_many(
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
        config.applications.update_one({"application_id": id}, {"$set": updates, "$push": pushes})
    else:
        config.applications.update_one({"application_id": id}, {"$set": updates})

    edited_application_link = "http://127.0.0.1:5001/api/v1.0/applications/" + id
    return make_response(jsonify({"url": edited_application_link}), 200)


# DELETE an application
# only rejected or withdrawn ones, so active or accepted records are kept
@application_routes.route("/api/v1.0/applications/<string:id>", methods=["DELETE"])
@jwt_required
@admin_required
def deleteApplication(id):
    application = config.applications.find_one({"application_id": id})
    if application is None:
        return make_response(jsonify({"error": "Application not found"}), 404)

    if application["application_status"] not in ["rejected", "withdrawn"]:
        return make_response(
            jsonify({"error": "Only rejected or withdrawn applications can be deleted"}), 409
        )

    config.applications.delete_one({"application_id": id})

    # removing the id from the student's previous applications too
    config.students.update_one(
        {"student_id": application["student_id"]},
        {"$pull": {"previous_applications": id}}
    )

    return make_response(jsonify({}), 204)