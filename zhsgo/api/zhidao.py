"""共享课（知到 / recruitAndCourseId）接口。

协议总结（来自抓包 + 反混淆前端）：
  * 所有业务参数 JSON 序列化后 AES-CBC 加密，塞进 `secretStr` 字段；
  * 同时明文带一个 `dateFormate` 毫秒时间戳；
  * 密钥按接口分组（HOME / VIDEO / QA / EXAM / AI）；
  * **所有时间戳必须走 `Pacer.ts_ms()`** —— 这是统一出口，别的地方不许自己造
    时间戳（原项目在这里硬编码 `int(time.time())*1000`，毫秒位恒为 000）。
"""
from __future__ import annotations

import json
from base64 import b64encode
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..crypto import HOME_KEY, VIDEO_KEY, AesCbc, get_ev
from ..errors import ApiError, CaptchaRequired
from ..net import HttpClient, endpoints as ep
from ..risk import Guard, Pacer
from ..util import AttrDict, wrap


class ZhidaoApi:
    # 上报参数里 `studyStatus` 恒定 0；`uuid + "zhs"` 是前端尾部标记
    UUID_SUFFIX = "zhs"

    def __init__(self, http: HttpClient, guard: Guard, pacer: Pacer,
                 uuid_provider: Callable[[], str]):
        self.http = http
        self.guard = guard
        self.pacer = pacer
        self.uuid_provider = uuid_provider
        self.guard.bind(http)

    # ------------------------------------------------------------- 传输

    def _encode(self, data: Dict[str, Any], key: bytes, encrypt: bool, stamp: bool) -> Dict[str, Any]:
        payload = dict(data)
        if stamp:
            payload["dateFormate"] = self.pacer.ts_ms()
        if encrypt:
            form: Dict[str, Any] = {"secretStr": AesCbc(key).encrypt(json.dumps(payload, ensure_ascii=False))}
        else:
            form = dict(payload)
        if stamp:
            form["dateFormate"] = payload["dateFormate"]
        return form

    def call(self, url: str, data: Dict[str, Any], *, key: bytes = VIDEO_KEY,
             encrypt: bool = True, ok_code: Any = 0, method: str = "POST",
             content_type: str = "form", stamp: bool = True,
             context: str = "", rac_id: Optional[str] = None) -> AttrDict:
        """带风控恢复的请求。每次重发都重新加密（密文含随机 IV）。"""

        def send() -> AttrDict:
            form = self._encode(data, key, encrypt, stamp)
            if method.upper() == "POST":
                return self.http.post(url, form, content_type=content_type)
            return self.http.get(url, form, content_type=content_type)

        ret = send()
        if ok_code is not None and ret.code != ok_code:
            if ret.code == ep.CODE_CAPTCHA:
                ret = self.guard.call(lambda: ret, send,
                                      context=context or url, rac_id=rac_id, ok_code=ok_code)
            if ret.code != ok_code:
                raise ApiError(ret.code, ret.get("message") or json.dumps(
                    {k: v for k, v in ret.items() if k != "data"}, ensure_ascii=False,
                    default=str), url)
        return ret

    # ------------------------------------------------------------- 课程

    def share_course_list(self, page_size: int = 10) -> List[AttrDict]:
        """全部共享课。"""
        out: List[AttrDict] = []
        page = 1
        while True:
            ret = self.call(
                ep.ZHIDAO_SHARE_LIST,
                {"status": 0, "pageNo": page, "pageSize": page_size},
                key=HOME_KEY, ok_code=ep.CODE_OK_HOME, context="查询共享课列表",
            )
            result = ret.result
            result.default = None
            courses = result.courseOpenDtos or []
            out.extend(courses)
            total = int(result.totalCount or 0)
            if not courses or len(out) >= total:
                break
            page += 1
            if page > 200:          # 防御性上限
                break
        return out

    def cross_site_login(self, rac_id: str) -> None:
        """跨站登录：给 studyh5 域建立会话。

        这个端点是导航/跳转型：正常响应就是 HTML 落地页，会话经 302 链
        建立在 cookie 里。上游 fuckZHS 同样只发请求、从不解析响应体 ——
        一旦按 JSON 解析，就会在真正拉课之前抛「响应不是 JSON」。
        """
        self.http.get(ep.ZHIDAO_GOLOGIN, {
            "fromurl": f"https://studyh5.zhihuishu.com/videoStudy.html#/studyVideo?recruitAndCourseId={rac_id}"
        }, expect_json=False)

    def course_info(self, rac_id: str) -> AttrDict:
        return self.call(ep.ZHIDAO_QUERY_COURSE, {"recruitAndCourseId": rac_id},
                         context="查询课程信息", rac_id=rac_id).data

    def video_list(self, rac_id: str) -> AttrDict:
        return self.call(ep.ZHIDAO_VIDEO_LIST, {"recruitAndCourseId": rac_id},
                         context="查询视频列表", rac_id=rac_id).data

    def study_state(self, lesson_ids: Sequence, video_ids: Sequence, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_STUDY_INFO, {
            "lessonIds": list(lesson_ids),
            "lessonVideoIds": list(video_ids),
            "recruitId": recruit_id,
        }, context="查询学习状态", ok_code=0).data

    def study_read_before(self, course_id: Any, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_STUDY_READ_BEFORE,
                         {"courseId": course_id, "recruitId": recruit_id},
                         ok_code=None).data

    def last_video(self, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_LAST_VIDEO, {"recruitId": recruit_id},
                         context="查询最近观看").data

    # ------------------------------------------------------------- 单视频

    def prelearning_note(self, rac_id: str, video: AttrDict, course_id: Any,
                         recruit_id: Any) -> AttrDict:
        ret = self.call(ep.ZHIDAO_PRELEARNING_NOTE, {
            "ccCourseId": course_id,
            "chapterId": video.chapterId,
            "isApply": 1,
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "recruitId": recruit_id,
            "videoId": video.videoId,
        }, context="获取 learningToken", rac_id=rac_id)
        return ret.data

    @staticmethod
    def learning_token(note: AttrDict) -> str:
        raw = note.studiedLessonDto.id
        return b64encode(str(raw).encode()).decode()

    def pointer_info(self, rac_id: str, video: AttrDict, course_id: Any, recruit_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_POINTER_INFO, {
            "lessonId": video.lessonId,
            "lessonVideoId": video.id,
            "recruitId": recruit_id,
            "courseId": course_id,
        }, context="获取弹题位置", rac_id=rac_id).data

    def popup_exam(self, rac_id: str, video: AttrDict, question_ids: Any,
                   time_sec: Any = 0) -> AttrDict:
        # pointerInfo 返回的 questionIds 是逗号分隔字符串（如 "100001"），
        # 前端原样把它放进 payload；再带上题目触发时间 time。
        if isinstance(question_ids, str):
            ids = question_ids.strip()
        elif isinstance(question_ids, (list, tuple, set)):
            ids = ",".join(str(x).strip() for x in question_ids if str(x).strip())
        else:
            ids = str(question_ids) if question_ids is not None else ""
        payload = {
            "lessonId": video.lessonId,
            "time": int(float(time_sec or 0)),
            "questionIds": ids,
        }
        # 单视频课时 smallLessonId=0，前端会直接删掉这个字段而不是传 0
        if video.id:
            payload["lessonVideoId"] = video.id
        return self.call(ep.ZHIDAO_POPUP_EXAM, payload,
                         context="拉取弹题", rac_id=rac_id).data

    def save_popup_answer(self, rac_id: str, video: AttrDict, course_id: Any,
                          recruit_id: Any, question_id: Any, answer_ids: str) -> AttrDict:
        payload = {
            "courseId": course_id,
            "recruitId": recruit_id,
            "testQuestionId": question_id,
            "isCurrent": "1",       # 前端原样传 1，字段名是 isCorrect 但值是 isCurrent
            "lessonId": video.lessonId,
            "answer": answer_ids,
            "testType": 0,
        }
        if video.id:
            payload["lessonVideoId"] = video.id
        # 2026-11 实测：弹题提交也走 VIDEO_KEY。旧版用 QA_KEY 会得到
        # code=-1「系统发生了不可预期的错误了」，与参数无关。
        return self.call(ep.ZHIDAO_POPUP_SAVE_ANSWER, payload,
                         key=VIDEO_KEY, context="提交弹题答案", rac_id=rac_id).data

    def three_dim_ware(self, rac_id: str, video_id: Any) -> AttrDict:
        return self.call(ep.ZHIDAO_THREE_DIM, {"videoId": video_id},
                         method="GET", context="三维课件", rac_id=rac_id).data

    # ------------------------------------------------------------- 进度上报

    def report_progress(self, rac_id: str, video: AttrDict, course: AttrDict,
                        played_time: float, last_submit: float, watch_point: str,
                        token_id: str, *, initial: bool = False) -> AttrDict:
        """学习进度上报。

        2026-11 前端实际协议（与旧版 fuckZHS 不同）：

        * 打开视频时：`saveDatabaseIntervalTimeV2`，10 字段，带 `courseId`
        * 播放过程中：`saveCacheIntervalTimeV2`，10 字段，不带 `courseId`

        两条链路的字段顺序也不同，不能混用。旧实现把“数据库层”的
        10 字段周期上报直接发给 V2，服务端解出来是错位的，于是
        `code=-1 参数解码发生错误`。
        """
        if not initial:
            return self.report_cache(rac_id, video, course, played_time,
                                     last_submit, watch_point, token_id)
        return self.report_db(rac_id, video, course, played_time,
                              last_submit, watch_point, token_id,
                              context="初始化学习进度" if abs(played_time - last_submit) < 1e-6 else "保存数据库进度")

    def report_db(self, rac_id: str, video: AttrDict, course: AttrDict,
                  played_time: float, last_submit: float, watch_point: str,
                  token_id: str, *, context: str = "保存数据库进度") -> AttrDict:
        """数据库层持久化上报（视频打开、视频完成、配额收工落盘时调用）。"""
        uuid = self.uuid_provider()
        total = int(max(0, played_time))
        raw_ev = [
            course.recruitId,
            video.lessonId,
            video.id,
            video.videoId,          # lastViewVideoId：当前视频即最近观看
            video.chapterId,
            0,                       # studyStatus，前端恒 0
            max(0, int(played_time - last_submit)),
            total,
            total,
            uuid + self.UUID_SUFFIX,
        ]
        data = {
            "ewssw": watch_point,
            "sdsew": get_ev(raw_ev),
            "zwsds": token_id,
            "courseId": course.courseInfo.courseId,
        }
        return self.call(ep.ZHIDAO_SAVE_DB_V2, data,
                         context=context, rac_id=rac_id).data

    def report_cache(self, rac_id: str, video: AttrDict, course: AttrDict,
                     played_time: float, last_submit: float, watch_point: str,
                     token_id: str) -> AttrDict:
        """播放过程中的缓存层上报。

        字段顺序来自 2026-11 H5 `svcpEveryOnceInAWhile`：
        recruitId, chapterId, courseId, lessonId, position,
        totalStudyTime, lastViewVideoId, smallLessonId, playTimes, uuid+"zhs"
        """
        uuid = self.uuid_provider()
        total = int(max(0, played_time))
        raw_ev = [
            course.recruitId,
            video.chapterId,
            course.courseInfo.courseId,
            video.lessonId,
            total,
            total,
            video.videoId,
            video.id,
            max(0, int(played_time - last_submit)),
            uuid + self.UUID_SUFFIX,
        ]
        return self.call(ep.ZHIDAO_SAVE_CACHE, {
            "ewssw": watch_point,
            "sdsew": get_ev(raw_ev),
            "zwsds": token_id,
        }, context="上报缓存进度", rac_id=rac_id).data
