from flask import Flask, make_response
from routes.auth_routes import auth_routes
from routes.property_routes import property_routes
from routes.application_routes import application_routes
from routes.student_routes import student_routes

app = Flask(__name__)

# connecting every group of routes to the app
app.register_blueprint(auth_routes)
app.register_blueprint(property_routes)
app.register_blueprint(application_routes)
app.register_blueprint(student_routes)


@app.route("/", methods=["GET"])
def indexPage():
    return make_response("<h1>Student Accommodation Finder API is running</h1>", 200)


if __name__ == "__main__":
    app.run(debug=True, port=5001)