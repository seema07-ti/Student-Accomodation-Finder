from flask import Blueprint, request, make_response, jsonify
from datetime import datetime, timedelta, timezone
import jwt
import bcrypt
import config
from security import jwt_required

# group for the login and logout routes
auth_routes = Blueprint("auth_routes", __name__)


# LOGIN using Basic Auth (username + password in Postman's Authorization tab)
# returns a token that lasts 30 minutes
@auth_routes.route("/api/v1.0/login", methods=["GET"])
def login():
    auth = request.authorization

    if auth:
        user = config.users.find_one({"username": auth.username})

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
                }, config.secret_key, algorithm="HS256")

                return make_response(jsonify({"token": token}), 200)
            else:
                return make_response(jsonify({"error": "Bad password"}), 401)
        else:
            return make_response(jsonify({"error": "Bad username"}), 401)

    return make_response(jsonify({"error": "Authentication required"}), 401)


# LOGOUT: puts the token on the blacklist so it can't be used again
@auth_routes.route("/api/v1.0/logout", methods=["GET"])
@jwt_required
def logout():
    token = request.headers.get("x-access-token")
    config.blacklist.insert_one({"token": token})
    return make_response(jsonify({"message": "Logout successful"}), 200)