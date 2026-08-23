from app import s, app
from flask import url_for

if __name__ == '__main__':
    with app.test_request_context():
        admin_token = s.dumps('admin', salt='admin-password-reset-salt')
        user_token = s.dumps('testuser@example.com', salt='password-reset-salt')
        print('ADMIN_RESET_URL:', url_for('admin_reset_with_token', token=admin_token, _external=False))
        print('USER_RESET_URL:', url_for('reset_with_token', token=user_token, _external=False))
