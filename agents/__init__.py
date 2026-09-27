"""Agents for VAST.

One agent per folder: `agents/<name>/` holds the conversation, its prompts, and
whatever that agent needs. Right now there is a single agent,
`agents/nextdim/`, and a second one is just another folder. `llm.py` is shared
for now and sits inside `nextdim`; move it to `agents/llm.py` once a second
agent needs it.
"""
