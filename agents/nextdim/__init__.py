"""The NextDim portal agent.

One folder per agent: the conversation, its prompts, and whatever that agent
needs. `agent.py` is the front door, `conversation.py` holds the state, and
`steps/` holds one module per part of the conversation. `llm.py` is shared for
now and sits inside `nextdim`; move it to `agents/llm.py` once a second agent
needs it.
"""
