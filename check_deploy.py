from app import app
from pathlib import Path

base = Path(app.root_path)
print('APP ROOT:', base)
print('TEMPLATES:', base / 'templates')
print('LOGIN TEMPLATE EXISTS:', (base / 'templates' / 'login.html').exists())
with app.test_client() as client:
    r = client.get('/login')
    print('GET /login:', r.status_code)
    if r.status_code != 200:
        raise SystemExit(1)
print('Deployment check passed.')
