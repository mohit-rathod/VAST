"""Version 0.2.1 snapshot; v0_2.json preserves the previous release evidence."""
import inspect
import json
import os
from pathlib import Path

from app.chat import ChatIn, ResetOut, TurnOut
from domain import models
from tools.available_slots import available_slots
from tools.match_clinics import nearest_candidates, nearest_clinics
from tools.rank_slots import rank_slots
from helpers import run_returning_conversation


def test_v0_2_1_snapshot(database):
    _, client, turns = run_returning_conversation()
    observed = {
        'conversation': turns,
        'model_requests': client.calls,
        'available_after_booking': available_slots(3,'2026-09-30'),
        'nearest_clinics': nearest_clinics(1,count=None),
        'nearest_candidates': nearest_candidates(1,'2026-09-30'),
        'rankings': {
            f'{speciality}:{period}:{at}': rank_slots(1,'2026-09-30',speciality,period,at)
            for speciality in (None,'ENT','oncology')
            for period in ('any','morning','afternoon','evening')
            for at in (None,'11:30')
        },
        'schemas': {
            name: cls.model_json_schema()
            for name,cls in vars(models).items()
            if inspect.isclass(cls) and issubclass(cls,models.BaseModel) and cls is not models.BaseModel
        },
        'api_schemas': {cls.__name__:cls.model_json_schema() for cls in (ChatIn,ResetOut,TurnOut)},
    }
    observed=json.loads(json.dumps(observed,default=str))
    path=Path(__file__).parent/'fixtures'/'v0_2_1.json'
    if os.getenv('VAST_WRITE_BASELINE') == '1':
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(observed,indent=2,sort_keys=True)+'\n')
    assert observed==json.loads(path.read_text())