from app import create_app

app = create_app()

if __name__ == "__main__":
    # For speed: disable the debug reloader by default.
    # Set DEBUG=1 in your environment when developing.
    import os

    debug = os.environ.get("DEBUG", "").strip() in {"1", "true", "True", "yes", "YES"}
    app.run(debug=debug)

