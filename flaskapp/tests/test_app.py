import pytest
import json
from unittest import mock
import os
import sys

# Add the parent directory to the path to import app.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the Flask app from the provided app.py file
# Assumes app.py is in the same directory or a directory that's been added to the path
from app import app, mysql

@pytest.fixture
def client():
    """
    Creates a test client for the Flask application.
    This fixture is used by all the tests to simulate requests.
    """
    # Configure the app for testing
    app.config['TESTING'] = True
    # Disable CSRF token checking for testing purposes
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as client:
        yield client

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """
    Mocks the environment variables used for the database connection.
    This prevents the app from trying to connect to a real database.
    """
    monkeypatch.setenv('MYSQL_DATABASE_USER', 'test_user')
    monkeypatch.setenv('MYSQL_DATABASE_PASSWORD', 'test_password')
    monkeypatch.setenv('MYSQL_DATABASE_DB', 'test_db')
    monkeypatch.setenv('MYSQL_DATABASE_HOST', 'localhost')

@pytest.mark.parametrize("route, expected_status_code", [
    ('/', 200),
    ('/showSignUp', 200),
    ('/showSignIn', 200),
    ('/showAddWish', 200)
])
@mock.patch('app.mysql.connect')
def test_get_routes(mock_connect, client, route, expected_status_code):
    """
    Tests various GET routes to ensure they return a 200 status code.
    This single test replaces four separate functions.
    """
    response = client.get(route)
    assert response.status_code == expected_status_code

@pytest.mark.parametrize("data, mock_db_result, expected_status, expected_response_part", [
    # Test case for a successful sign-up
    ({'inputName': 'Test User', 'inputEmail': 'test@example.com', 'inputPassword': 'password123'}, [], 200, {'message': 'User created successfully !'}),
    # Test case for a database error during sign-up
    ({'inputName': 'Test User', 'inputEmail': 'test@example.com', 'inputPassword': 'password123'}, [('An error occurred.',)], 200, {'error': str(('An error occurred.',))}),
    # Test case for missing form fields (Flask handles this with a 400 error)
    ({'inputName': 'Test User'}, [], 400, None),
])
@mock.patch('app.mysql.connect')
def test_sign_up(mock_connect, client, data, mock_db_result, expected_status, expected_response_part):
    """
    Tests the signUp route with different scenarios (success, DB error, missing fields).
    """
    mock_cursor = mock_connect.return_value.cursor.return_value
    mock_cursor.fetchall.return_value = mock_db_result
    
    response = client.post('/signUp', data=data)
    
    assert response.status_code == expected_status
    if expected_response_part:
        assert json.loads(response.data) == expected_response_part

@pytest.mark.parametrize("data, mock_db_result, expected_status, expected_redirect_location, expected_message", [
    # Test case for a successful login
    ({'inputEmail': 'test@example.com', 'inputPassword': 'password123'}, [('user_id', 'Test User', 'test@example.com', 'password123')], 302, '/userHome', None),
    # Test case for a wrong password
    ({'inputEmail': 'test@example.com', 'inputPassword': 'password123'}, [('user_id', 'Test User', 'test@example.com', 'wrong_password')], 200, None, b'Wrong Email address or Password'),
    # Test case for a user not found
    ({'inputEmail': 'nonexistent@example.com', 'inputPassword': 'password123'}, [], 200, None, b'Wrong Email address or Password'),
])
@mock.patch('app.mysql.connect')
def test_validate_login(mock_connect, client, data, mock_db_result, expected_status, expected_redirect_location, expected_message):
    """
    Tests the validateLogin route for success, wrong password, and user not found scenarios.
    """
    mock_cursor = mock_connect.return_value.cursor.return_value
    mock_cursor.fetchall.return_value = mock_db_result
    
    response = client.post('/validateLogin', data=data)
    
    assert response.status_code == expected_status
    if expected_redirect_location:
        assert response.location == expected_redirect_location
        with client.session_transaction() as sess:
            assert sess['user'] == 'user_id'
    if expected_message:
        assert expected_message in response.data

@mock.patch('app.mysql.connect', side_effect=Exception('Test DB Error'))
def test_validate_login_exception(mock_connect, client):
    """
    Tests the exception handling in the validateLogin route.
    Mocks the database connection to raise an exception.
    """
    data = {'inputEmail': 'test@example.com', 'inputPassword': 'password123'}
    response = client.post('/validateLogin', data=data)
    
    assert response.status_code == 200
    assert b'Test DB Error' in response.data

@pytest.mark.parametrize("has_session, expected_status_code, expected_message_part", [
    (True, 200, b'Bucket List'),
    (False, 200, b'Unauthorized Access'),
])
def test_user_home(client, has_session, expected_status_code, expected_message_part):
    """
    Tests the userHome route with and without an active session.
    """
    with client.session_transaction() as sess:
        if has_session:
            sess['user'] = 'test_user_id'
        response = client.get('/userHome')
        assert response.status_code == expected_status_code
        assert expected_message_part in response.data

def test_logout(client):
    """
    Tests the logout route.
    Ensures the session is cleared and a redirect to the main page occurs.
    """
    with client.session_transaction() as sess:
        sess['user'] = 'test_user_id'
    response = client.get('/logout')
    
    assert response.status_code == 302
    assert response.location == '/'
    
    with client.session_transaction() as sess:
        assert 'user' not in sess

@pytest.mark.parametrize("has_session, data, mock_db_result, expected_status, expected_location, expected_message", [
    # Test case for successful wish addition
    (True, {'inputTitle': 'Test Wish', 'inputDescription': 'A description'}, [], 302, '/userHome', None),
    # Test case for a database error
    (True, {'inputTitle': 'Test Wish', 'inputDescription': 'A description'}, [('An error occurred!',)], 200, None, b'An error occurred!'),
    # Test case for unauthorized access (no session)
    (False, {'inputTitle': 'Test Wish', 'inputDescription': 'A description'}, [], 200, None, b'Unauthorized Access'),
    # Test case for database exception
    (True, {'inputTitle': 'Test Wish', 'inputDescription': 'A description'}, Exception('Add Wish Error'), 200, None, b'Add Wish Error'),
])
@mock.patch('app.mysql.connect')
def test_add_wish(mock_connect, client, has_session, data, mock_db_result, expected_status, expected_location, expected_message):
    """
    Tests the addWish route with different scenarios.
    """
    with client.session_transaction() as sess:
        if has_session:
            sess['user'] = 'test_user_id'
        
    if isinstance(mock_db_result, Exception):
        mock_connect.side_effect = mock_db_result
    else:
        mock_cursor = mock_connect.return_value.cursor.return_value
        mock_cursor.fetchall.return_value = mock_db_result
    
    response = client.post('/addWish', data=data)
    
    assert response.status_code == expected_status
    if expected_location:
        assert response.location == expected_location
    if expected_message:
        assert expected_message in response.data

@pytest.mark.parametrize("has_session, mock_db_result, expected_status, expected_message", [
    # Test case for successful wish retrieval
    (True, [
        (1, 'Title 1', 'Desc 1', 'test_user_id', '2023-01-01'),
        (2, 'Title 2', 'Desc 2', 'test_user_id', '2023-01-02')
    ], 200, None),
    # Test case for unauthorized access
    (False, [], 200, b'Unauthorized Access'),
    # Test case for a database exception
    (True, Exception('Get Wish Error'), 200, b'Get Wish Error'),
])
@mock.patch('app.mysql.connect')
def test_get_wish(mock_connect, client, has_session, mock_db_result, expected_status, expected_message):
    """
    Tests the getWish route with different scenarios.
    """
    with client.session_transaction() as sess:
        if has_session:
            sess['user'] = 'test_user_id'

    if isinstance(mock_db_result, Exception):
        mock_connect.side_effect = mock_db_result
    else:
        mock_cursor = mock_connect.return_value.cursor.return_value
        mock_cursor.fetchall.return_value = mock_db_result

    response = client.get('/getWish')

    assert response.status_code == expected_status
    if expected_message:
        assert expected_message in response.data
    else:
        wishes_dict = json.loads(response.data)
        expected_data = [
            {'Id': 1, 'Title': 'Title 1', 'Description': 'Desc 1', 'Date': '2023-01-01'},
            {'Id': 2, 'Title': 'Title 2', 'Description': 'Desc 2', 'Date': '2023-01-02'}
        ]
        assert wishes_dict == expected_data
