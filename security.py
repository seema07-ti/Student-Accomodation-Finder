from flask import request, make_response, jsonify
from functools import wraps
import jwt
import config


# checks that a valid token is sent in the x-access-token header
def jwt_required(func):
    @wraps(func)
    def jwt_required_wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")

        if not token:
            return make_response(jsonify({"error": "Token is missing"}), 401)

        try:
            jwt.decode(token, config.secret_key, algorithms=["HS256"])
        except jwt.InvalidTokenError:     # wrong, changed or expired token
            return make_response(jsonify({"error": "Token is invalid or expired"}), 401)

        # token was cancelled by logout
        if config.blacklist.find_one({"token": token}) is not None:
            return make_response(jsonify({"error": "Token has been cancelled"}), 401)

        return func(*args, **kwargs)
    return jwt_required_wrapper


# checks that the logged in user is an admin
# always used under @jwt_required, so the token is already checked
def admin_required(func):
    @wraps(func)
    def admin_required_wrapper(*args, **kwargs):
        token = request.headers.get("x-access-token")
        data = jwt.decode(token, config.secret_key, algorithms=["HS256"])

        if data["role"] != "admin":
            return make_response(jsonify({"error": "Admin access required"}), 403)

        return func(*args, **kwargs)
    return admin_required_wrapper