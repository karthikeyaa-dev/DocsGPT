from application.app import create_app
from application.core.settings import settings

app = create_app()

if __name__ == "__main__":
    app.run(debug=settings.FLASK_DEBUG_MODE, port=7091)
