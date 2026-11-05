"""进度上报字段顺序的回归测试（不联网）。

2026-11 前端把“初始 DB 上报”和“周期 Cache 上报”拆成两套不同的
10 字段格式。字段错一位服务端就回 code=-1，所以这里把顺序钉死。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zhsgo.api.zhidao import ZhidaoApi
from zhsgo.crypto.ev import rev_ev
from zhsgo.util import AttrDict


class Dummy:
    pass


def make_api():
    api = object.__new__(ZhidaoApi)
    api.uuid_provider = lambda: "UUID"
    api.captured = {}

    def call(url, data, **kwargs):
        api.captured = {"url": url, "data": data, "kwargs": kwargs}
        return AttrDict({"code": 0, "data": {"submitSuccess": True}})

    api.call = call
    return api


VIDEO = AttrDict({
    "id": 0, "videoId": 500001, "lessonId": 300001, "chapterId": 400001,
    "videoSec": 300,
})
COURSE = AttrDict({"recruitId": 100001, "courseInfo": {"courseId": 200001}})


def test_initial_db_fields():
    api = make_api()
    api.report_progress("rac", VIDEO, COURSE, 20, 20, "0,1", "TOKEN", initial=True)
    assert api.captured["url"].endswith("/saveDatabaseIntervalTimeV2")
    raw = rev_ev(api.captured["data"]["sdsew"])
    assert raw == "100001;300001;0;500001;400001;0;0;20;20;UUIDzhs", raw
    assert api.captured["data"]["courseId"] == 200001


def test_periodic_cache_fields():
    api = make_api()
    api.report_progress("rac", VIDEO, COURSE, 35, 20, "2,3", "TOKEN")
    assert api.captured["url"].endswith("/saveCacheIntervalTimeV2")
    raw = rev_ev(api.captured["data"]["sdsew"])
    assert raw == "100001;400001;200001;300001;35;35;500001;0;15;UUIDzhs", raw
    assert "courseId" not in api.captured["data"]


if __name__ == "__main__":
    test_initial_db_fields()
    test_periodic_cache_fields()
    print("progress format tests PASS")
