from flask import Blueprint, request, redirect, url_for
from datetime import datetime
from your_app.models import db, User, EmailVerification  # adjust imports
from flask import jsonify

auth = Blueprint("auth", __name__)

@auth.route("/verify-email")
def verify_email():
    token = request.args.get("token")
    if not token:
        return jsonify({"error": "Token is missing"}), 400

    try:
        payload = decode_token(token)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Check expiration
    if payload["exp"] < int(time.time()):
        return jsonify({"error": "Token has expired"}), 400

    # Consume nonce from Redis (single-use)
    user_id = consume_nonce(payload["nonce"])
    if user_id is None:
        return jsonify({"error": "Token already used or invalid"}), 400

    # Mark user verified
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 400

    user.is_verified = True
    user.is_active = True
    db.session.commit()

    return jsonify({"message": "Email verified successfully!"})

