"""Conversation entry point; steps own business flows and controls own lifecycle."""
import threading
from app.trace import STEP
from domain.phone import PhoneNumberError
from services.duration import appointment_duration
from . import replies, controls
from .conversation import Context, DONE, Flow, STEP_LABELS, CLINIC, SLOTS, BOOK, DETAILS, COMPLAINT
from .steps import HANDLERS


class NextDimAgent:
    def __init__(self, client=None, on_event=None, verification=None):
        self.flow = Flow()
        self.context = Context(self.flow, client, on_event, verification)
        self._lock = threading.RLock()

    @property
    def turn_lock(self):
        """Let the adapter bind events and snapshot a turn under the same lock."""
        return self._lock

    @property
    def on_event(self):
        return self.context.on_event

    @on_event.setter
    def on_event(self, callback):
        self.context.on_event = callback

    @property
    def step(self):
        return self.flow.step

    @property
    def patient(self):
        return self.flow.patient

    @property
    def booking(self):
        return self.flow.booking

    @property
    def actions(self):
        return controls.actions(self.flow)

    @property
    def booking_history(self):
        return self.flow.booking_history

    def start(self):
        self.flow.last_reply = replies.welcome()
        return self.flow.last_reply

    def handle(self, message: str, *, resolve_actions: bool = False) -> str:
        # Serialize same-session confirmations as well as database reservations.
        with self._lock:
            reply = self._handle(message.strip(), resolve_actions=resolve_actions)
            self.flow.last_reply = reply
            return reply

    def _handle(self, message: str, *, resolve_actions: bool = False) -> str:
        if self.flow.finished:
            return replies.after_booking() if self.booking else replies.ended()
        # Do not emit raw intake, contact details or verification codes to the UI trace.
        self.context.emit(STEP, STEP_LABELS.get(self.step, self.step), step=self.step)
        try:
            # Browser turns may ask the LLM to resolve natural language against
            # the actions currently visible in that same state. Exact button
            # payloads remain deterministic; non-browser/internal callers retain
            # the previous behaviour unless they opt in.
            if resolve_actions:
                from .action_intent import resolve as resolve_visible_action
                canonical_action = resolve_visible_action(self.context, message)
                if canonical_action is not None:
                    message = canonical_action

            controlled = controls.handle(self.context, message)
            if controlled is not None:
                return controlled
            from .answers import is_yes
            from services.contact_input import error_reply
            if self.flow.contact_errors and is_yes(message):
                return error_reply(self.flow.contact_errors)
            if self.flow.editing and is_yes(message):
                return "Please provide the correction, or choose Keep current details."
            scheduling = self.step in {CLINIC, SLOTS, BOOK}
            request = appointment_duration(message, scheduling=scheduling)
            if request.error:
                if scheduling:
                    self.flow.options, self.flow.chosen, self.flow.step = [], None, CLINIC
                return request.error
            prefix = ""
            if request.minutes is not None:
                changed = self.flow.duration_minutes != request.minutes
                self.flow.duration_minutes = request.minutes
                prefix = "I am trying to find a slot for 1 hour. " if request.minutes == 60 else "I will look for a 30-minute appointment. "
                if self.step == BOOK and not changed:
                    return HANDLERS[BOOK](self.context, message)
                if scheduling:
                    from .steps import scheduling as schedule
                    if changed:
                        self.flow.options, self.flow.chosen = [], None
                        self.flow.step = CLINIC
                    from services.date_resolver import resolve_time
                    from tools.available_slots import now
                    remaining = request.remaining
                    temporal = schedule.RESOLVER.resolve(remaining, now(schedule._zone(self.flow)))
                    if temporal.recognized or resolve_time(remaining).mentioned:
                        return prefix + schedule.ask_when(self.context, remaining)
                    if self.flow.preference:
                        return prefix + schedule.offer(self.context)
                    return prefix + replies.ask_time(schedule._zone(self.flow))
                if self.step == COMPLAINT and not self.flow.complaint:
                    return prefix + replies.ask_problem(self.flow.first_name)
                # Pure duration requests must not make a model invent intake details.
                if self.step == DETAILS and not any(c in request.remaining for c in ("@", "+")):
                    return prefix + replies.ask_details()
            return prefix + HANDLERS[self.step](self.context, message)
        except PhoneNumberError as error:
            return str(error)
        except ValueError:
            return "Sorry, I did not quite catch that. Could you say it another way?"


if __name__ == "__main__":
    agent = NextDimAgent()
    print(agent.start())
    while not agent.flow.finished:
        try:
            print(agent.handle(input("> ")))
        except (EOFError, KeyboardInterrupt):
            break