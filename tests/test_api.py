import pytest
from fastapi.testclient import TestClient
from app import chat, sessions
from app.main import app
from agents.nextdim.agent import NextDimAgent
from helpers import INTAKE, ScriptedClient


@pytest.fixture
def client(database,monkeypatch):
    sessions.SESSIONS.clear()
    monkeypatch.setattr(chat,'OPENAI_API_KEY','test-key-not-real')
    monkeypatch.setattr(sessions,'NextDimAgent',lambda **kw: NextDimAgent(client=ScriptedClient(INTAKE),**kw))
    with TestClient(app) as client:
        yield client
    sessions.SESSIONS.clear()


def test_health_root_and_config(client):
    assert client.get('/health').json()['status']=='ok'
    assert client.get('/api/config').json()['ready'] is True
    response=client.get('/')
    assert response.status_code==200 and 'text/html' in response.headers['content-type']


def test_reset_and_chat_contract(client):
    reset=client.post('/api/reset',json={}).json()
    assert set(reset)=={'session_id','reply'}
    result=client.post('/api/chat',json={'session_id':reset['session_id'],'message':'details'}).json()
    assert set(result)=={'session_id','reply','step','done','events','booking','actions','bookings'}
    assert result['session_id']==reset['session_id'] and result['step']=='verify'
    assert not result['done'] and result['booking'] is None
    assert len(result['events'])==3
    verified=client.post('/api/chat',json={'session_id':reset['session_id'],'message':'246810'}).json()
    assert verified['step']=='registry'
    again=client.post('/api/chat',json={'session_id':reset['session_id'],'message':'yes'}).json()
    assert again['step']=='menu' and len(again['events'])==1
    replacement=client.post('/api/reset',json={'session_id':reset['session_id']}).json()
    assert replacement['session_id']!=reset['session_id'] and reset['session_id'] not in sessions.SESSIONS


@pytest.mark.parametrize('payload',[{}, {'message':''}, {'message':'x'*2001}])
def test_message_validation(client,payload):
    assert client.post('/api/chat',json=payload).status_code==422


def test_missing_key(client,monkeypatch):
    monkeypatch.setattr(chat,'OPENAI_API_KEY','')
    response=client.post('/api/chat',json={'message':'hi'})
    assert response.status_code==503 and response.json()['detail'].startswith('OPENAI_API_KEY is not set.')


def test_unknown_session_returns_usable_new_id(client):
    result=client.post('/api/chat',json={'session_id':'stale-session','message':'details'}).json()
    assert result['session_id']!='stale-session' and result['session_id'] in sessions.SESSIONS
    assert len(sessions.SESSIONS)==1


@pytest.mark.parametrize('error,detail',[(RuntimeError('failure'),'failure'),(ValueError('bad'),'The model could not be used: bad')])
def test_http_exception_mapping(client,error,detail):
    session_id=client.post('/api/reset',json={}).json()['session_id']
    def fail(_): raise error
    sessions.SESSIONS[session_id].handle=fail
    response=client.post('/api/chat',json={'session_id':session_id,'message':'test'})
    assert response.status_code==502 and response.json()=={'detail':detail}


def test_session_capacity_preserves_clear_all_policy(client,monkeypatch):
    monkeypatch.setattr(sessions,'MAX_SESSIONS',2)
    first,_=sessions.new_session()
    second,_=sessions.new_session()
    third,_=sessions.new_session()
    assert set(sessions.SESSIONS)=={third} and first!=second


def test_session_creation_error_is_not_remapped_to_502(client,monkeypatch):
    def fail(**kwargs):
        raise RuntimeError('session creation failed')
    monkeypatch.setattr(sessions,'NextDimAgent',fail)
    with pytest.raises(RuntimeError,match='session creation failed'):
        client.post('/api/chat',json={'message':'hi'})


@pytest.mark.parametrize('message', ['end chat', 'please end the chat', 'bye'])
def test_end_chat_api_needs_no_model_key(client, monkeypatch, message):
    monkeypatch.setattr(chat, 'OPENAI_API_KEY', '')
    turn = client.post('/api/chat', json={'message': message}).json()
    assert turn['step'] == 'end_confirm' and not turn['done']
    assert [a['message'] for a in turn['actions']] == ['yes', 'no']
    ended = client.post('/api/chat', json={'session_id': turn['session_id'], 'message': 'yes'}).json()
    assert ended['done'] and not ended['actions'] and ended['booking'] is None
    again = client.post('/api/chat', json={'session_id': turn['session_id'], 'message': 'yes'}).json()
    assert again['done'] and 'ended' in again['reply']


def test_history_api_requires_verified_session_and_scopes_records(client):
    from app import db
    with db.connect() as conn:
        conn.executemany("INSERT INTO bookings(clinic_id,patient_id,slot_date,start_time,end_time,status) VALUES (?,?,?,?,?,?)", [
            (1, 1, '2026-09-01', '09:00', '09:30', 'completed'),
            (2, 1, '2026-10-01', '10:00', '11:00', 'booked'),
            (3, 2, '2026-10-01', '10:00', '10:30', 'booked'),
        ])
    sid = client.post('/api/reset', json={}).json()['session_id']
    def turn(message):
        response = client.post('/api/chat', json={'session_id': sid, 'message': message})
        assert response.status_code == 200
        return response.json()
    assert turn('my bookings')['bookings'] is None
    turn('details')
    assert turn('my bookings')['bookings'] is None
    turn('246810')
    menu = turn('yes')
    assert any(a['message'] == 'my bookings' for a in menu['actions'])
    history = turn('my bookings')
    assert len(history['bookings']) == 2
    assert {b['clinic_id'] for b in history['bookings']} == {1, 2}
    assert 'Thursday 2026-10-01' in history['reply']
    assert 'Clinic C' not in history['reply']


def test_booking_api_closes_without_extra_end_confirmation(client, monkeypatch):
    from helpers import COMPLAINT
    monkeypatch.setattr(sessions, 'NextDimAgent', lambda **kw: NextDimAgent(client=ScriptedClient(INTAKE, COMPLAINT), **kw))
    sid = client.post('/api/reset', json={}).json()['session_id']
    for message in ['details', '246810', 'yes', 'book appointment', 'ear trouble', 'yes', 'Wednesday at 11 am', '1', 'yes']:
        response = client.post('/api/chat', json={'session_id': sid, 'message': message})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result['done'] and result['booking']['ok'] and result['actions'] == []
    assert 'Wednesday 2026-09-30' in result['reply'] and 'chat is now closed' in result['reply']


def test_action_script_is_served_as_javascript(client):
    response = client.get('/static/chat-actions.js')
    assert response.status_code == 200
    assert 'javascript' in response.headers['content-type']
    assert 'class ChatActionRenderer' in response.text
    assert '/static/chat-actions.js' in client.get('/').text
    assert client.get('/static/../config.py').status_code == 404


def test_natural_confirmation_api_books_the_selected_slot(client, monkeypatch):
    from helpers import COMPLAINT
    monkeypatch.setenv('VAST_REQUIRE_EMAIL_VERIFICATION', 'false')
    monkeypatch.setattr(sessions, 'NextDimAgent', lambda **kw: NextDimAgent(
        client=ScriptedClient(INTAKE, COMPLAINT, {'intent': 'confirm'}), **kw))
    sid = client.post('/api/reset', json={}).json()['session_id']
    for message in ['details', 'yes', 'book appointment', 'ear trouble', 'yes', 'Wednesday morning']:
        response = client.post('/api/chat', json={'session_id': sid, 'message': message})
        assert response.status_code == 200, response.text
    options = response.json()
    slot = next(a for a in options['actions'] if a.get('kind') == 'slot')
    selected = client.post('/api/chat', json={'session_id': sid, 'message': slot['message']}).json()
    assert selected['step'] == 'book' and any(a['label'] == 'Confirm booking' for a in selected['actions'])
    booked = client.post('/api/chat', json={'session_id': sid, 'message': 'I confirm this slot'}).json()
    assert booked['done'] and booked['booking']['ok'] and booked['actions'] == []