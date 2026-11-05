"""学习编排 —— 全部节拍、配额、风控恢复的汇合点。

对照原实现（fucker.py 的 `fuckZhidaoVideo` / `fuckHikeVideo`），这里的结构性改动：

  1. 上报间隔不再写死 30 秒，由 `Pacer.next_report_interval()` 逐次抽取；
  2. 时间戳不再就地 `int(time.time())*1000`，统一走 `Pacer.ts_ms()`；
  3. 暂停时**仍然按节拍上报**（playTimes≈0），而不是只在暂停瞬间补一枪；
  4. 观看点每批不回头重报 0,1；
  5. 每个视频开始前过一遍 `Budget`（会话时长 / 单日总量 / 单课时限）；
  6. 所有 sleep 走 `Clock`，所以整条循环可以在测试里用假时钟秒跑完。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..ai import Answerer, PopupSolver
from ..app import App
from ..errors import (
    AuthError,
    BudgetExhausted,
    CaptchaRequired,
    RiskError,
    Stopped,
    TimeLimitExceeded,
    ZhsError,
)
from ..logger import get as log
from ..net import endpoints as ep
from ..net.client import TransportError
from ..observer import PHASE_DONE, PHASE_REST, PHASE_STUDY, NullObserver, Observer, Progress
from ..risk import WatchPoint
from ..util import AttrDict, progress_bar, shorten


@dataclass
class ZhidaoContext:
    rac_id: str
    course: AttrDict
    chapters: AttrDict
    videos: Dict[str, AttrDict]
    course_id: Any
    recruit_id: Any
    fucked_time: float = 0.0


@dataclass
class HikeContext:
    course_id: Any
    root: List[AttrDict] = field(default_factory=list)
    fucked_time: float = 0.0


class StudyRunner:
    def __init__(self, app: App, observer: Optional[Observer] = None):
        self.app = app
        self.observer: Observer = observer or NullObserver()
        self.cfg = app.cfg
        self.scfg = app.cfg.study
        self.clock = app.clock
        self.pacer = app.pacer
        self.budget = app.budget
        self.zhidao = app.zhidao
        self.hike = app.hike
        self.http = app.http
        # 弹题作答器：服务端有答案就直接用；没有答案时按题型调用模型/启发式。
        # getattr 是为了兼容测试里的 FakeApp（不装配 LLM 后端）。
        backend = getattr(app, "backend", lambda: None)()
        self.answerer = Answerer(backend, self.cfg.ai.context)
        self.popup_solver = PopupSolver(self.answerer, self.cfg.ai.context)
        self._zhidao_ctx: Dict[str, ZhidaoContext] = {}
        self._hike_ctx: Dict[str, HikeContext] = {}
        # run_all 会吞掉单门课的错误（否则一门课挂了其余课也不刷），
        # 这里把错误记下来，交给 daily.py 判断“是真学完了还是全都失败了”。
        self.last_course_errors: List[str] = []
        self.last_course_count = 0

    # ================================================================== 分派

    def run_course(self, course_id: str, kind: Optional[str] = None,
                   video_ids: Optional[List[str]] = None) -> None:
        """按课程 ID 跑一门课。

        `kind` 来自 list_courses() 的 type，最可靠；手动传 ID 时：
          * 含字母 → 共享课的 secret，直接走共享课；
          * 纯数字 → 可能是 hike courseId，也可能是共享课的纯数字 racId，
            先试共享课，接口报错再回退 hike。原实现“纯数字一律 hike”
            会把 `recruitAndCourseId=48111` 这种共享课直接跑错。
        """
        cid = str(course_id)
        if kind == "zhidao":
            self.run_zhidao_course(cid, video_ids=video_ids)
            return
        if kind == "hike":
            self.run_hike_course(cid, video_ids=video_ids)
            return
        if any(ch.isalpha() for ch in cid):
            self.run_zhidao_course(cid, video_ids=video_ids)
            return
        try:
            self.run_zhidao_course(cid, video_ids=video_ids)
        except (BudgetExhausted, Stopped, TimeLimitExceeded, RiskError, AuthError):
            # 配额/风控/登录态问题不是“课程类型不对”，不能拿回退掩盖。
            raise
        except Exception as exc:
            log().warning(f"按共享课跑 {cid} 失败（{exc}），回退校内课")
            self.run_hike_course(cid, video_ids=video_ids)

    def list_courses(self) -> List[dict]:
        out: List[dict] = []
        errors: List[str] = []
        try:
            for c in self.zhidao.share_course_list():
                out.append({
                    "type": "zhidao",
                    "name": c.get("courseName") or c.get("courseInfo", {}).get("name", ""),
                    "id": c.get("secret"),
                })
        except (AuthError, CaptchaRequired, RiskError):
            raise
        except ZhsError as e:
            errors.append(f"共享课列表: {e}")
            log().error(f"拉取共享课列表失败: {e}")
        try:
            for c in self.hike.course_list():
                out.append({
                    "type": "hike",
                    "name": c.get("courseName", ""),
                    "id": str(c.get("courseId")),
                })
        except (AuthError, CaptchaRequired, RiskError):
            raise
        except ZhsError as e:
            errors.append(f"校内课列表: {e}")
            log().error(f"拉取校内课列表失败: {e}")
        if not out and errors:
            self.last_course_errors.extend(errors)
        return out

    def run_all(self) -> None:
        self.last_course_errors = []
        courses = self.list_courses()
        self.last_course_count = len(courses)
        if not courses:
            log().warning("课程清单为空：可能是登录态失效、课程不在当前接口范围，或接口改版")
            return
        for c in courses:
            if self.observer.should_stop():
                raise Stopped("用户停止")
            try:
                self.run_course(c["id"], kind=c.get("type"))
            except Stopped:
                raise
            except BudgetExhausted:
                raise
            except Exception as e:
                msg = f"{c.get('name', '')}({c.get('id', '')}): {e}"
                self.last_course_errors.append(msg)
                log().error(f"课程 {msg} 处理失败")

    # ================================================================== 共享课

    def zhidao_context(self, rac_id: str, force: bool = False) -> ZhidaoContext:
        if rac_id in self._zhidao_ctx and not force:
            return self._zhidao_ctx[rac_id]

        log().info(f"拉取共享课上下文 {rac_id}")
        self.zhidao.cross_site_login(rac_id)
        course = self.zhidao.course_info(rac_id)
        chapters = self.zhidao.video_list(rac_id)
        course_id = chapters.get("courseId")
        recruit_id = course.get("recruitId")

        lesson_ids: List[Any] = []
        videos: Dict[str, AttrDict] = {}
        for chapter in chapters.get("videoChapterDtos") or []:
            for lesson in chapter.get("videoLessons") or []:
                lesson_ids.append(lesson.get("id"))
                if "videoId" in lesson:
                    # 单视频课时：把它自己包成一个 smallLesson
                    single = lesson.copy()
                    single.lessonId = lesson.get("id")
                    single.id = 0
                    lesson["videoSmallLessons"] = [single]
                for v in lesson.get("videoSmallLessons") or []:
                    v["chapterId"] = chapter.get("id")
                    videos[str(v.get("videoId"))] = v

        states: AttrDict = self.zhidao.study_state(
            lesson_ids, [v.get("id") for v in videos.values() if v.get("id")], recruit_id)
        lv = states.get("lv") or {}
        by_lesson = states.get("lesson") or {}
        for v in videos.values():
            st = lv.get(str(v.get("id"))) or by_lesson.get(str(v.get("lessonId"))) or {}
            v["watchState"] = st.get("watchState")
            v["studyTotalTime"] = st.get("studyTotalTime") or 0

        ctx = ZhidaoContext(rac_id=rac_id, course=course, chapters=chapters,
                            videos=videos, course_id=course_id, recruit_id=recruit_id)
        self._zhidao_ctx[rac_id] = ctx
        log().info(f"{len(lesson_ids)} 个课时 / {len(videos)} 个视频")
        return ctx

    def run_zhidao_course(self, rac_id: str,
                          video_ids: Optional[List[str]] = None) -> None:
        ctx = self.zhidao_context(rac_id)
        name = ctx.course.get("courseInfo", {}).get("name") or rac_id
        log().info(f"开始共享课：{name}")
        target_vids = {str(v) for v in video_ids} if video_ids else None
        chapters = ctx.chapters.get("videoChapterDtos") or []
        for chapter in chapters:
            self._tree_print(1, f"章节 {chapter.get('name')}")
            for lesson in chapter.get("videoLessons") or []:
                self._tree_print(2, f"课时 {lesson.get('name')}")
                for video in lesson.get("videoSmallLessons") or []:
                    if target_vids and str(video.get("videoId")) not in target_vids and str(video.get("id")) not in target_vids:
                        continue
                    self._tree_print(3, f"视频 {video.get('name')}")
                    try:
                        self.run_zhidao_video(ctx, video)
                    except (Stopped, BudgetExhausted, AuthError):
                        raise
                    except TimeLimitExceeded as e:
                        log().warning(f"本课时限用尽，跳过剩余视频: {e}")
                        return
                    except CaptchaRequired as e:
                        log().error(f"风控未能解除，本课程中断: {e}")
                        raise
                    except Exception as e:
                        log().error(f"视频 {video.get('videoId')} 处理失败: {e}")
        log().info(f"共享课完成：{name}")
        self.observer.progress(Progress(phase=PHASE_DONE, course=name,
                                        message=f"共享课完成：{name}"))

    # -------------------------------------------------------------- 单视频

    def run_zhidao_video(self, ctx: ZhidaoContext, video: AttrDict) -> None:
        rac = ctx.rac_id
        vid = str(video.get("videoId"))
        total_sec = float(video.get("videoSec") or 0)
        played = float(video.get("studyTotalTime") or 0)

        if video.get("watchState") == 1 and self.scfg.end_threshold <= 1.0:
            log().debug(f"跳过已完成视频 {vid}")
            return

        rest = self.budget.before_video(rac)
        if rest > 0:
            log().warning(f"会话休息 {rest / 60:.0f} 分钟")
            self.observer.progress(Progress(
                phase=PHASE_REST, course=self._course_name(ctx),
                message=f"会话休息 {rest / 60:.0f} 分钟",
                current=0, total=rest))
            self._rest(rest)

        token = self.zhidao.learning_token(
            self.zhidao.prelearning_note(rac, video, ctx.course_id, ctx.recruit_id))

        questions = self._load_questions(ctx, video, played)

        end_time = max(total_sec * self.scfg.end_threshold, 1.0)
        if questions:
            end_time = max(float(questions[0].get("timeSec") or 0), end_time)
        # 若服务端 watchState 仍未置 1，但历史 played 已超过 end_threshold（如 91%~99%），
        # 必须补齐到视频完整时长（或至少再推进一段并落库），否则循环 0 tick 空转无法完课。
        if played >= end_time:
            if total_sec > played:
                end_time = total_sec
            else:
                end_time = played + 2.0
        end_time = min(end_time, self.scfg.max_video_seconds)

        if self.scfg.prime_video:
            self.prime_video(video.get("videoId"))
        self.zhidao.three_dim_ware(rac, video.get("videoId"))

        wp = WatchPoint(interval=2, init=int(played))
        last_submit = played
        since_report = 0.0
        next_report = self.pacer.next_report_interval()
        sample_acc = 0.0
        idle = 0.0
        quiz: Optional[AttrDict] = None
        quiz_delay = 0.0

        warn = self.pacer.clamp_warning(self.scfg.speed)
        if warn:
            log().warning(warn)

        if self.scfg.initial_report:
            wp.add(played)
            self.zhidao.report_progress(rac, video, ctx.course, played, played,
                                        wp.take(played), token, initial=True)

        log().info(f"学习中 {shorten(str(video.get('name') or vid), 40)} | "
                   f"{played:.0f}/{total_sec:.0f}s | 目标 {end_time:.0f}s")
        video_name = str(video.get("name") or vid)
        course_name = self._course_name(ctx)
        self.observer.progress(Progress(
            phase=PHASE_STUDY, course=course_name, video=video_name,
            message=f"开始 {video_name}", current=played, total=end_time))

        while played < end_time:
            # 用户点的暂停/停止在这里生效，响应延迟不超过一个 tick
            self.observer.gate()
            if self.observer.should_stop():
                raise Stopped("用户停止")

            # tick 时长本身带抖动：原实现的裸 sleep(1) 会把上报间隔量化成整数秒，
            # 抹掉本该存在的自然抖动
            tick = self.pacer.tick_seconds()
            self.clock.sleep(tick)
            ctx.fucked_time += tick
            try:
                self.budget.tick(tick, rac)
            except BudgetExhausted:
                # 到达每日上限时 tick 会立刻抛异常。此时 played 已经推进，
                # 但最近一次上报可能在 20~40 秒前 —— 强制补一枪数据库层持久化，避免
                # “今天看满 25 分钟，服务端只记了 24 分半”或缓存过期丢失进度。
                try:
                    wp.add(played)
                    self.zhidao.report_progress(rac, video, ctx.course, played,
                                                last_submit, wp.take(played), token,
                                                initial=True)
                    last_submit = played
                    video["studyTotalTime"] = played
                    self.budget.save()
                    log().info("已达今日额度，补报最后一次数据库进度后收工")
                except Exception as report_error:
                    log().warning(f"收工前进度补报失败（不影响明天继续）: {report_error}")
                raise
            since_report += tick
            sample_acc += tick

            if idle > 0:
                idle -= tick
            else:
                played = min(played + self.pacer.speed(self.scfg.speed) * tick, end_time)
                pause = self.pacer.roll_pause()
                if pause > 0:
                    idle = pause
                    # 暂停是真前端会发生的上报事件，但不是立刻发一个 1 秒间隔的
                    # 请求（那反而突兀）；隔几秒补一次 playTimes≈0 的报告
                    since_report = 0.0
                    next_report = random.uniform(2.5, 9.0)

            if sample_acc >= 2.0:
                sample_acc = 0.0
                wp.add(played)

            # ---- 弹题
            if quiz is None and quiz_delay <= 0 and questions:
                nxt = questions[-1]
                if played >= float(nxt.get("timeSec") or 0):
                    quiz = self._fetch_quiz(ctx, video, questions.pop())
                    if quiz is not None:
                        quiz_delay = random.uniform(*self.scfg.quiz_delay)
            if quiz is not None:
                if quiz_delay > 0:
                    quiz_delay -= tick
                    idle = max(idle, tick)          # 看题时视频是暂停的
                else:
                    self._submit_quiz(ctx, video, quiz)
                    quiz = None

            # ---- 上报
            if since_report >= next_report or played >= end_time:
                is_final = played >= end_time
                wp.add(played)
                wp_str = wp.take(played)
                try:
                    if is_final:
                        # 视频到达目标进度时走 saveDatabaseIntervalTimeV2 落库，
                        # 保证服务端持久化解算 watchState=1
                        self.zhidao.report_progress(rac, video, ctx.course, played,
                                                    last_submit, wp_str, token,
                                                    initial=True)
                    else:
                        self.zhidao.report_progress(rac, video, ctx.course, played,
                                                    last_submit, wp_str, token)
                    last_submit = played
                    video["studyTotalTime"] = played
                    since_report = 0.0
                    next_report = self.pacer.next_report_interval()
                    self.budget.save()
                except TransportError as exc:
                    if is_final:
                        raise
                    # 播放中途偶发单次网络超时：保留累计时长和观看点，下个周期一起补报
                    for pt in wp_str.split(","):
                        if pt.strip().isdigit():
                            wp._pending.append(int(pt.strip()))
                    since_report = 0.0
                    next_report = random.uniform(8.0, 16.0)
                    log().warning(f"周期进度上报网络波动，将在 {next_report:.0f}s 后合并重试: {exc}")

            if self.scfg.progress_view:
                prefix = "暂停中" if idle > 0 else f"观看 {vid}"
                if quiz is not None:
                    prefix = "答题中"
                progress_bar(played, end_time, prefix=prefix, suffix="完成")

            self.observer.progress(Progress(
                phase=PHASE_STUDY, course=course_name, video=video_name,
                message=f"学习中 {video_name}",
                current=played, total=end_time,
                extra={"reported": last_submit, "idle": idle > 0, "quiz": quiz is not None}))

        if self.scfg.progress_view:
            progress_bar(end_time, end_time, prefix=f"完成 {vid}", suffix="")

        self.observer.progress(Progress(
            phase=PHASE_STUDY, course=course_name, video=video_name,
            message=f"完成 {video_name}", current=end_time, total=end_time))

        self.clock.sleep(random.uniform(0.5, 2.0))
        # 更新本地进度，避免同一进程内重复处理时重刷
        video["studyTotalTime"] = max(played, end_time)
        video["watchState"] = 1

        rest = self.pacer.rest_between_videos()
        if rest > 0.5:
            log().debug(f"视频间休息 {rest:.0f}s")
            self._rest(rest, course_name)

    # -------------------------------------------------------------- 辅助

    def _course_name(self, ctx: ZhidaoContext) -> str:
        return str(ctx.course.get("courseInfo", {}).get("name") or ctx.rac_id)

    def _rest(self, seconds: float, course: str = "") -> None:
        """可中断的休息。

        直接 `clock.sleep(rest)` 的话，用户点了停止/暂停要等这段休息
        走完才响应 —— 一次会话休息就是几十分钟，体验上等于卡死。
        """
        if seconds <= 0:
            return
        left = float(seconds)
        step = 0.5
        while left > 0:
            self.observer.gate()
            if self.observer.should_stop():
                raise Stopped("用户停止（休息中）")
            chunk = min(step, left)
            self.clock.sleep(chunk)
            left -= chunk
            if course:
                self.observer.progress(Progress(
                    phase=PHASE_REST, course=course,
                    message=f"休息中，剩余 {left / 60:.1f} 分钟",
                    current=seconds - left, total=seconds))

    def _load_questions(self, ctx: ZhidaoContext, video: AttrDict,
                        played: float) -> List[AttrDict]:
        try:
            info = self.zhidao.pointer_info(ctx.rac_id, video, ctx.course_id, ctx.recruit_id)
        except ZhsError as e:
            log().warning(f"拉取弹题位置失败: {e}")
            return []
        items = list(info.get("questionPoint") or [])
        if not items:
            return []
        items.sort(key=lambda x: float(x.get("timeSec") or 0), reverse=True)
        while items and float(items[-1].get("timeSec") or 0) <= played:
            items.pop()
        return items

    def _fetch_quiz(self, ctx: ZhidaoContext, video: AttrDict, point: AttrDict) -> Optional[AttrDict]:
        try:
            ret = self.zhidao.popup_exam(ctx.rac_id, video,
                                         point.get("questionIds") or "",
                                         point.get("timeSec") or 0)
            items = ret.get("lessonTestQuestionUseInterfaceDtos") or []
            if not items:
                return None
            return items[0].get("testQuestion")
        except Exception as e:
            log().error(f"拉取弹题内容失败: {e}")
            return None

    def _submit_quiz(self, ctx: ZhidaoContext, video: AttrDict, quiz: AttrDict) -> None:
        qid = quiz.get("questionId")
        try:
            answer = self.popup_solver.solve(quiz)
            if not answer:
                log().warning(f"弹题 {qid} 无法生成答案，跳过（不阻塞视频）")
                return
            self.zhidao.save_popup_answer(ctx.rac_id, video, ctx.course_id,
                                          ctx.recruit_id, qid, answer)
            log().info(f"弹题 {qid} 已提交: {answer[:120]}")
        except Exception as e:
            log().error(f"提交弹题失败: {e}")

    def prime_video(self, video_id: Any) -> None:
        """拉一次播放地址，并对媒体头部或第一个分片发一个 Range GET —— 让 CDN 侧留下真实流量痕迹。"""
        try:
            raw = self.http.get(ep.VIDEO_INIT, {
                "jsonpCallBack": "result",
                "videoID": str(video_id),
                "_": self.pacer.ts_ms(),
            })
            lines = ((raw.get("result") or {}).get("lines") or [])
            if not lines:
                return
            url = lines[0].get("lineUrl")
            if not url:
                return
            resp = self.http.raw_get(url, stream=True, headers={"Range": "bytes=0-65535"})
            try:
                if hasattr(resp, "iter_content"):
                    chunk = next(resp.iter_content(chunk_size=4096), b"")
                    text = chunk.decode("utf-8", errors="ignore")
                else:
                    text = getattr(resp, "text", "")[:2000]
            finally:
                if hasattr(resp, "close"):
                    resp.close()
            if "#EXTM3U" in text:
                # HLS：再取一个分片的前 64KB
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        base = url.rsplit("/", 1)[0]
                        seg_url = line if line.startswith("http") else f"{base}/{line}"
                        seg_resp = self.http.raw_get(seg_url, stream=True,
                                                     headers={"Range": "bytes=0-65535"})
                        try:
                            if hasattr(seg_resp, "iter_content"):
                                next(seg_resp.iter_content(chunk_size=4096), b"")
                        finally:
                            if hasattr(seg_resp, "close"):
                                seg_resp.close()
                        break
        except Exception as e:
            log().debug(f"预热视频流失败（不影响学习）: {e}")

    def _tree_print(self, depth: int, text: str) -> None:
        if self.scfg.tree_view:
            print(f"{'  |' * depth}__{text}")

    # ================================================================== 校内课

    def hike_context(self, course_id: str, force: bool = False) -> HikeContext:
        if course_id in self._hike_ctx and not force:
            return self._hike_ctx[course_id]
        root = self.hike.menu_tree(course_id)
        ctx = HikeContext(course_id=course_id, root=root)
        self._hike_ctx[course_id] = ctx
        log().info(f"校内课 {course_id} 顶层章节 {len(root)} 个")
        return ctx

    def run_hike_course(self, course_id: str,
                        video_ids: Optional[List[str]] = None) -> None:
        ctx = self.hike_context(course_id)
        log().info(f"开始校内课 {course_id}")
        target_vids = {str(v) for v in video_ids} if video_ids else None
        for chapter in ctx.root:
            try:
                self._hike_walk(ctx, chapter, 1, target_vids=target_vids)
            except (Stopped, BudgetExhausted, AuthError):
                raise
            except TimeLimitExceeded as e:
                log().warning(f"时限用尽: {e}")
                return
            except CaptchaRequired as e:
                log().error(f"风控未解除: {e}")
                raise
        log().info(f"校内课 {course_id} 完成")
        self.observer.progress(Progress(phase=PHASE_DONE, course=str(course_id),
                                        message=f"校内课 {course_id} 完成"))

    def _hike_walk(self, ctx: HikeContext, node: AttrDict, depth: int,
                   target_vids: Optional[set] = None) -> None:
        if self.observer.should_stop():
            raise Stopped("用户停止")
        children = node.get("childList")
        if children:
            self._tree_print(depth, f"章节 {node.get('name')}")
            for child in children:
                self._hike_walk(ctx, child, depth + 1, target_vids=target_vids)
            return

        file = node
        if target_vids and str(file.get("id")) not in target_vids:
            return
        self._tree_print(depth, f"文件 {file.get('name')}")
        study_time = float(file.get("studyTime") or 0)
        total_time = float(file.get("totalTime") or 0)
        if total_time > 0 and study_time >= total_time * self.scfg.end_threshold:
            log().debug(f"跳过已完成文件 {file.get('id')}")
            return

        data_type = file.get("dataType")
        try:
            if data_type == 3:
                self.run_hike_video(ctx, file.get("id"), study_time)
            elif data_type is None:
                self._tree_print(depth, "## 未支持的文件类型（可能是测验）")
            else:
                self.hike.view_file(ctx.course_id, file.get("id"))
                self.clock.sleep(random.uniform(1.0, 3.0))
        except (BudgetExhausted, Stopped, AuthError, CaptchaRequired, RiskError):
            raise
        except Exception as e:
            log().error(f"处理文件 {file.get('id')} 失败: {e}")

    def run_hike_video(self, ctx: HikeContext, file_id: Any, prev_time: float = 0.0) -> None:
        course_id = ctx.course_id
        rest = self.budget.before_video(str(course_id))
        if rest > 0:
            log().warning(f"会话休息 {rest / 60:.0f} 分钟")
            self._rest(rest, str(course_id))

        info = self.hike.view_file(course_id, file_id)
        if self.scfg.prime_video:
            self.prime_video(info.get("dataId"))

        total = int(float(info.get("totalTime") or 0))
        end_time = max(total * self.scfg.end_threshold, 1.0)
        start_date = self.pacer.ts_ms()
        played = float(prev_time)
        since_report = 0.0
        next_report = self.pacer.next_report_interval()
        idle = 0.0

        log().info(f"学习中 {shorten(str(info.get('name') or file_id), 40)} | "
                   f"{played:.0f}/{total}s")

        while played < end_time:
            self.observer.gate()
            if self.observer.should_stop():
                raise Stopped("用户停止")

            tick = self.pacer.tick_seconds()
            self.clock.sleep(tick)
            ctx.fucked_time += tick
            self.budget.tick(tick, str(course_id))
            since_report += tick

            if idle > 0:
                idle -= tick
            else:
                played = min(played + self.pacer.speed(self.scfg.speed) * tick, end_time)
                idle = self.pacer.roll_pause()

            if played >= end_time or since_report >= next_report:
                ret = self.hike.save_record(course_id, file_id, played, prev_time, start_date)
                # 服务端返回的是它认定的累计时间，比我们自己的大就采纳；
                # 但**绝不把 played 回退** —— 原实现直接 `played = ret`，
                # 一旦服务端返回值原地不动，`while played <= end_time` 就永远成立
                prev_time = ret
                start_date = self.pacer.ts_ms()
                if ret > played:
                    played = min(ret, end_time)
                since_report = 0.0
                next_report = self.pacer.next_report_interval()
                self.budget.save()

            if self.scfg.progress_view:
                progress_bar(played, end_time, prefix=f"观看 {file_id}", suffix="完成")

            self.observer.progress(Progress(
                phase=PHASE_STUDY, course=str(course_id),
                video=str(info.get("name") or file_id),
                message=f"学习中 {info.get('name') or file_id}",
                current=played, total=end_time))

        self.clock.sleep(random.uniform(0.5, 2.0))
        rest = self.pacer.rest_between_videos()
        if rest > 0.5:
            self._rest(rest, str(course_id))
