from datetime import date
from decimal import Decimal
import pytest
from wechat_work_recorder.models import WorkKind, WorkRecord
from wechat_work_recorder.wps_clipboard import to_wps_tsv

def test_wps_columns_piece_and_hour():
    records = [
        WorkRecord("AM-1011", date(2026,10,9), WorkKind.PIECE, "一群", "", "8513-7", Decimal("70"), Decimal("1.7")),
        WorkRecord("AM-1011", date(2026,10,9), WorkKind.HOURLY, "一群", "", hours=Decimal("3.5")),
    ]
    lines = to_wps_tsv(records, {"AM-1011":"陪陪"}).splitlines()
    assert lines[0].split("\t") == ["2026/10/09","AM-1011","陪陪","","8513-7","","70","1.7","119.00"]
    assert lines[1].split("\t") == ["2026/10/09","AM-1011","陪陪","","计时","","3.5","15","52.50"]

def test_unknown_employee_blocked():
    r = WorkRecord("missing",date(2026,10,9),WorkKind.HOURLY,"一群","",hours=Decimal("2"))
    with pytest.raises(ValueError):
        to_wps_tsv([r], {})
