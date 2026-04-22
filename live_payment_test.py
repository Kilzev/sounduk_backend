import requests
import uuid
import sys

BASE_URL = 'http://127.0.0.1:8000/api'

def main():
    username = f'user_{uuid.uuid4().hex[:8]}'
    email = f'{username}@example.com'
    password = 'password123'

    print(f'1. Registering user: {username}')
    r = requests.post(f'{BASE_URL}/auth/register', json={
        'username': username,
        'email': email,
        'password': password
    })
    if r.status_code not in [200, 201]:
        print(f'FAILED Register status={r.status_code}: {r.text}')
        sys.exit(1)

    print('2. Logging in...')
    r = requests.post(f'{BASE_URL}/auth/login', json={
        'username': username,
        'password': password
    })
    if r.status_code != 200:
        print(f'FAILED Login status={r.status_code}: {r.text}')
        sys.exit(1)

    token = r.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    print('3. Creating payment...')
    # Using correct product_id from source code
    r = requests.post(f'{BASE_URL}/payments/create', json={
        'product_id': 'storage_pack_3gb'
    }, headers=headers)

    if r.status_code in [200, 201]:
        data = r.json()
        confirmation_url = data.get('confirmation_url')
        print(f'Payment created! URL: {confirmation_url}')

        # Check for mock
        if 'mock' in confirmation_url:
             print('WARNING: Received MOCK payment URL.')
        else:
             print('SUCCESS: Received REAL payment URL.')
    else:
        print(f'FAILED Create Payment status={r.status_code}: {r.text}')
        sys.exit(1)

if __name__ == '__main__':
    main()
