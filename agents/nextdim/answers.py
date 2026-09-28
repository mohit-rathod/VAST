"""The three ways a patient can answer, as far as plain code can tell.

The model is asked for structured answers wherever there is something to ask
for: a name, a date, a problem, which appointment they mean. These are the cases
it is not worth a call for, because a patient who says "yes" or "2" has already
been clear enough.

What is left out on purpose is a number inside a sentence. "2pm" is a time and
"option 2" is a choice, and only the model can tell them apart, so those replies
are handed on rather than guessed at here.
"""

import re

# Words that mean yes here. "No" is deliberately not in the set: a patient who
# says "no" is disagreeing, and every step that reads this offers them a way to
# say what they meant instead.
YES = {
    "yes",
    "y",
    "yeah",
    "yep",
    "yup",
    "ok",
    "okay",
    "sure",
    "correct",
    "right",
    "same",
    "confirmed",
    "no change",
    "that works",
    "that will do",
    "sounds good",
    "perfect",
    "go ahead",
    "book it",
    "do it",
    "please do",
    "all right",
    "alright",
    "happy with that",
}

# A list option said as nothing but its number.
BARE = re.compile(r"^[^0-9a-z]*([1-9])[^0-9a-z]*$")

# Words that pick the first option without a number, so "the first one" and "yes"
# both land on the same booking.
FIRST = {"1", "first", "one", "the first one", "the first", "nearest", "closest"}


def is_yes(message: str) -> bool:
    """True when the patient is agreeing with what the agent just said."""
    text = message.strip().lower().rstrip(".! ")
    return text in YES or text in {"yes please", "yes, please", "yes, book it", "yes book it", "yes confirm"}


def picked_number(message: str, count: int) -> int | None:
    """The option the patient chose, as a zero-based index, or None.

    "yes" and "no change" mean the first option when there is one, which is what
    a patient means by them after being shown a list. A number is only taken when
    it is all the reply is, so a time of day is never read as a choice.
    """
    if count == 0:
        return None
    text = message.strip().lower().rstrip(".")
    if is_yes(text) or text in FIRST:
        return 0
    ordinal = re.fullmatch(r"(?:the )?(second|third|fourth|fifth)(?: one)?", text)
    if ordinal:
        index = {"second": 1, "third": 2, "fourth": 3, "fifth": 4}[ordinal[1]]
        return index if index < count else None
    bare = BARE.match(text)
    if bare is None:
        return None
    number = int(bare.group(1))
    return number - 1 if 1 <= number <= count else None