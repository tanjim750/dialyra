from flask import Flask, request, jsonify
from asterisk_ami.ami_service import AMIService
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
ami = AMIService()

@app.route("/api/call", methods=["POST"])
def make_call():
    data = request.json

    phone = data.get("phone")

    result = ami.originate_call(phone)

    return jsonify({
        "status": "initiated",
        "phone": phone,
        "response": str(result)
    })

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=True
    )