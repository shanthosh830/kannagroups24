from app import create_app

app = create_app()
with app.app_context():
    with app.test_client() as c:
        r = c.get('/design/1?lang=en')
        print("Status:", r.status_code)
        if r.status_code == 500:
            print(r.data.decode('utf-8'))
