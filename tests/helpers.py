import copy
import json
from types import SimpleNamespace


class ScriptedClient:
    """Only the SDK surface the app actually uses, with deterministic replies."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if not self.answers:
            raise AssertionError('Unexpected model call')
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


INTAKE = dict(first_name='Test', last_name='Patient', email='test@example.test', phone='2125550100')
COMPLAINT = dict(description='Ear trouble', speciality='ENT', understood_as='Your ear is troubling you', detail='')
PREFERENCE = dict(date='2026-09-30', weekday='Wednesday', period='morning', at=None, outside=False)


def run_returning_conversation():
    from agents.nextdim.agent import NextDimAgent
    events = []
    client = ScriptedClient(INTAKE, COMPLAINT)
    agent = NextDimAgent(client=client, on_event=events.append)
    turns = [{'reply': agent.start(), 'step': agent.step}]
    for message in ('My details', '246810', 'yes', 'book appointment', 'Ear trouble', 'yes', 'Wednesday morning', '1', 'yes', 'thanks'):
        events.clear()
        reply = agent.handle(message)
        turns.append(dict(message=message, reply=reply, step=agent.step, booking=agent.booking, events=copy.deepcopy(events)))
    return agent, client, turns


class MemorySender:
    """Explicit test-only delivery adapter; never installed in application code."""
    def __init__(self):
        self.sent = []
    def send(self, email, code):
        self.sent.append((email, code))