from flask import request, jsonify, Response
from pydantic import BaseModel, ValidationError
from functools import wraps


def _dump(model: BaseModel):
    return model.dict() if hasattr(model, "dict") else model.model_dump()


def validate_schema(
    input_schema: type[BaseModel] | None = None,
    response_schema: type[BaseModel] | None = None,
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            # -------- Input validation --------
            if input_schema:
                data = request.get_json(silent=True)
                if data is None:
                    return jsonify({"error": "Invalid or missing JSON body"}), 400
                try:
                    kwargs["validated_data"] = input_schema(**data)
                except ValidationError as e:
                    return jsonify({"errors": e.errors()}), 422

            # -------- Call endpoint --------
            try:
                result = func(*args, **kwargs)
            except ValueError as e:
                # Handle ValueError exceptions, like password validation errors
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                # Catch all other exceptions
                return (
                    jsonify(
                        {"error": "An unexpected error occurred", "details": str(e)}
                    ),
                    500,
                )

            # If already a Flask response, return it untouched
            if isinstance(result, Response):
                return result

            # Handle (data, status_code)
            if isinstance(result, tuple):
                result, status = result
            else:
                status = 200

            # -------- Response validation --------
            if response_schema:
                try:
                    if isinstance(result, BaseModel):
                        result = _dump(result)
                    result = response_schema(**result)
                    return jsonify(_dump(result)), status
                except ValidationError as e:
                    return (
                        jsonify(
                            {
                                "error": "Response validation failed",
                                "details": e.errors(),
                            }
                        ),
                        500,
                    )

            return jsonify(result), status

        return wrapper

    return decorator
