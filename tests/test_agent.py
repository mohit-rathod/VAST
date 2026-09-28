import pytest
from agents.nextdim.agent import NextDimAgent
from agents.nextdim.answers import is_yes, picked_number
from agents.nextdim.conversation import BOOK, CLINIC, COMPLAINT, DONE, REGISTRY, SLOTS
from agents.nextdim.llm import ask
from agents.nextdim.steps import scheduling
from domain.models import Availability, Complaint, Confirmation, PatientIntake, SlotOption
from tools.book import book_appointment
from tools.patients import read
from helpers import COMPLAINT as COMPLAINT_DATA, INTAKE, PREFERENCE, ScriptedClient, run_returning_conversation


@pytest.mark.parametrize('text,expected',[('yes',True),('yes please',True),('no',False),('YES.',True),('not sure',False)])
def test_confirmation_shortcuts(text,expected):
    assert is_yes(text) is expected


@pytest.mark.parametrize('text,count,expected',[('1',3,0),('2',3,1),('3',3,2),('4',3,None),('yes',0,None),('2pm',3,None),('option 2',3,None)])
def test_number_parser(text,count,expected):
    assert picked_number(text,count)==expected


def test_returning_patient_end_to_end(database):
    agent,client,turns=run_returning_conversation()
    assert [turn['step'] for turn in turns]==['details','verify',REGISTRY,'menu',COMPLAINT,COMPLAINT,CLINIC,SLOTS,BOOK,DONE,DONE]
    assert agent.booking['clinic_id']==1  # Displayed option 1 must book the first option.
    assert len(client.calls)==2 and not client.answers
    assert read(1)['complaints']=='Ear trouble'


def test_new_patient_flow(database):
    intake={**INTAKE,'email':'new@example.test','phone':'2125550199'}
    address=dict(address='New Street',city='New York',state='NY',zip='10001')
    agent=NextDimAgent(client=ScriptedClient(intake,address))
    agent.handle('My details')
    assert agent.patient is None and agent.step==REGISTRY
    agent.handle('My address')
    assert agent.flow.pending is not None
    agent.handle('yes')
    assert agent.patient['id']==3 and agent.step==REGISTRY
    agent.handle('yes')
    assert agent.step==COMPLAINT


def test_partial_intake(database):
    agent=NextDimAgent(client=ScriptedClient({'first_name':'Test'}))
    response=agent.handle('Test')
    assert agent.step=='details' and 'your last name' in response


def prepare_scheduling(client):
    agent=NextDimAgent(client=client)
    agent.flow.patient=read(1)
    agent.flow.complaint=Complaint(**COMPLAINT_DATA)
    agent.flow.step=CLINIC
    return agent


@pytest.mark.parametrize('preference',[{'outside':True},{},{'date':'2026-10-10'},{'date':'2020-01-01'}])
def test_invalid_preference_does_not_offer(database,preference):
    agent=prepare_scheduling(ScriptedClient(preference))
    reply=agent.handle('another day')
    assert reply and agent.step==CLINIC and not agent.flow.options


def test_language_pick_is_one_based(database):
    agent=prepare_scheduling(ScriptedClient({'number':1}))
    agent.handle('Wednesday morning')
    agent.handle('Clinic A')
    assert agent.step==BOOK and agent.flow.chosen==agent.flow.options[0]


def test_booking_taken_reoffers(database):
    agent=prepare_scheduling(ScriptedClient({'number':1}))
    agent.handle('Wednesday morning')
    agent.handle('Clinic A')
    selected=agent.flow.chosen
    assert book_appointment(selected.clinic_id,2,selected.date,f'{selected.start_time:%H:%M}')['ok']
    reply=agent.handle('yes')
    assert agent.step==SLOTS and agent.booking is None and 'taken by another patient' in reply


def test_model_success_and_events():
    events=[]
    result=ask(Confirmation,'system',{'message':'yes'},client=ScriptedClient({'agreed':True}),on_event=events.append,label='Confirm')
    assert result.agreed and [event['title'] for event in events]==['Confirm','The model answered']


def test_invalid_model_reply_retries_once():
    client=ScriptedClient('not json',{'agreed':True})
    assert ask(Confirmation,'system',{},client=client).agreed
    assert len(client.calls)==2


def test_value_error_fallback():
    agent=NextDimAgent(client=ScriptedClient(ValueError('bad response')))
    assert agent.handle('details')=='Sorry, I did not quite catch that. Could you say it another way?'