"""The steps of the NextDim conversation, one module each.

A step is a function of a Context and the patient's message that returns the
reply, and nothing else: it reads what the flow knows, decides what happens next,
and hands over to the next step by setting `flow.step`. `HANDLERS` is the whole
state machine, which is what `NextDimAgent.handle` dispatches through.

    details      the name, email and phone a patient is identified by
    registry     whether they are registered, and what we hold about them
    complaint    the problem, restated until the patient agrees with it
    scheduling   the clinic that treats it, and the slot they will be given
    booking      the agreed slot, written down
"""

from ..conversation import BOOK, CLINIC, COMPLAINT, DETAILS, REGISTRY, SLOTS
from . import booking, complaint, details, registry, scheduling, account
from ..conversation import VERIFY, RECOVERY, RECOVERY_ID, CONTACT_CONFIRM, MENU

HANDLERS = {
    DETAILS: details.handle,
    REGISTRY: registry.handle,
    COMPLAINT: complaint.handle,
    CLINIC: scheduling.ask_when,
    SLOTS: scheduling.choose,
    BOOK: booking.book,
    VERIFY: account.verify,
    RECOVERY: account.collect_contacts,
    RECOVERY_ID: account.recover_identity,
    CONTACT_CONFIRM: account.save_contacts,
    MENU: account.menu,
}