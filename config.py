from pymongo import MongoClient

# shared settings every route file needs
secret_key = "safsecretkey-student-accommodation-2026"   # used to sign and check tokens

# connecting to mongodb and the student accommodation database
client = MongoClient("mongodb://localhost:27017/")
db = client.AccDB
properties = db.properties
students = db.student
applications = db.application
users = db.user
blacklist = db.blacklist   # tokens of users who logged out

