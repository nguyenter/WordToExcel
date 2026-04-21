from werkzeug.security import generate_password_hash
import re

from app.models import User
from app.dao.auth_dao import (
    get_user_by_email,
    create_user,
    commit,
    rollback
)


def register_user(data):
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    username = data.get("username", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not first_name or not last_name:
        return {"error": "Ho va ten khong duoc de trong"}

    if not username:
        return {"error": "Username khong duoc de trong"}

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return {"error": "Email khong hop le"}

    if len(password) < 6:
        return {"error": "Password >= 6 ky tu"}

    if get_user_by_email(email):
        return {"error": "Email da ton tai"}

    try:

        user = User(
            first_name=first_name,
            last_name=last_name,
            username=username,
            email=email,
            password=generate_password_hash(password),
            phone_number=data.get("phone_number"),
        )

        create_user(user)

        commit()

        return {
            "message": "Dang ky thanh cong",
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user.role.value
            }
        }

    except Exception as e:
        rollback()
        return {"error": str(e)}