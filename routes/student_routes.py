from flask import Blueprint, request, make_response, jsonify
import jwt
import config
from security import jwt_required, admin_required

# group for the student routes and the admin analytics
student_routes = Blueprint("student_routes", __name__)


# GET all students with pagination (admin)
# e.g. /api/v1.0/students?pn=1&ps=10
@student_routes.route("/api/v1.0/students", methods=["GET"])
@jwt_required
@admin_required
def getAllStudents():
    try:
        page_num = int(request.args.get("pn", 1))
        page_size = int(request.args.get("ps", 5))

        if page_num < 1 or page_size < 1:
            return make_response(
                jsonify({"error": "Page number and page size must be positive"}), 400
            )

        page_start = page_size * (page_num - 1)

        data_to_return = []

        for student in config.students.find().skip(page_start).limit(page_size):
            student["_id"] = str(student["_id"])

            # changing the _id inside each array into text
            for contact in student.get("emergency_contacts", []):
                contact["_id"] = str(contact["_id"])

            for check in student.get("verification_history", []):
                check["_id"] = str(check["_id"])

            data_to_return.append(student)

        return make_response(jsonify(data_to_return), 200)

    except ValueError:
        return make_response(
            jsonify({"error": "Page number and page size must be integers"}), 400
        )


# GET one student's applications
# a student can only see their own, an admin can see anyone's
# e.g. /api/v1.0/students/STU001/applications
@student_routes.route("/api/v1.0/students/<string:id>/applications", methods=["GET"])
@jwt_required
def getStudentApplications(id):
    # reading who is logged in from the token
    token = request.headers.get("x-access-token")
    data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

    # students can only ask for their own applications
    if data["role"] != "admin" and data["linked_id"] != id:
        return make_response(jsonify({"error": "You can only view your own applications"}), 403)

    if config.students.find_one({"student_id": id}) is None:
        return make_response(jsonify({"error": "Student not found"}), 404)

    data_to_return = []

    for application in config.applications.find({"student_id": id}):
        application["_id"] = str(application["_id"])

        for history in application.get("status_history", []):
            history["_id"] = str(history["_id"])

        for payment in application.get("deposit_payments", []):
            payment["_id"] = str(payment["_id"])

        for note in application.get("landlord_notes", []):
            note["_id"] = str(note["_id"])

        data_to_return.append(application)

    return make_response(jsonify(data_to_return), 200)


# GET analytics: average rent per campus and room demand
# uses mongodb aggregation pipelines
@student_routes.route("/api/v1.0/accommodation/analytics", methods=["GET"])
@jwt_required
@admin_required
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
    for result in config.properties.aggregate(pipeline):
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
    for result in config.applications.aggregate(pipeline):
        applications_by_status.append({"status": result["_id"], "count": result["count"]})

    # 3. top 5 properties with the most applications (room demand)
    most_wanted_properties = []
    pipeline = [
        {"$group": {"_id": "$property_id", "applications": {"$sum": 1}}},
        {"$sort": {"applications": -1}},
        {"$limit": 5}
    ]
    for result in config.applications.aggregate(pipeline):
        most_wanted_properties.append({"property_id": result["_id"], "applications": result["applications"]})

    return make_response(jsonify({
        "rent_by_campus": rent_by_campus,
        "applications_by_status": applications_by_status,
        "most_wanted_properties": most_wanted_properties
    }), 200)