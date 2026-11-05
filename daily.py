#!/usr/bin/env python3
"""每日 25 分钟学习入口。

与 `main.py` 的区别：
  * 只学 `budget.daily_minutes` 分钟就退出，不追求一次刷完；
  * 用 `state/daily_status.json` + `state/daily_history.jsonl` 记录每天结果；
  * 同一时间只允许一个实例，避免两个进程同时写 state；
  * 未登录时给出明确退出码，方便 Windows 计划任务/通知判断。

典型用法：
    python daily.py --login          # 第一次：扫码登录并保存 cookie
    python daily.py                  # 之后每天跑一次，学满 25 分钟退出
    python daily.py --status         # 查看今天学了多少
    python daily.py --fetch          # 拉课程清单
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zhsgo.app import App  # noqa: E402
from zhsgo.config import Config  # noqa: E402
from zhsgo.errors import (  # noqa: E402
    AuthError,
    BudgetExhausted,
    CaptchaRequired,
    RiskLocked,
    Stopped,
    ZhsError,
)
from zhsgo.logger import get as log  # noqa: E402
from zhsgo.runner import StudyRunner  # noqa: E402
from zhsgo.util import stderr_safe  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(ROOT, "state", "daily_status.json")
HISTORY_FILE = os.path.join(ROOT, "state", "daily_history.jsonl")
LOCK_FILE = os.path.join(ROOT, "state", "daily.lock")
NEED_LOGIN = os.path.join(ROOT, "state", "NEED_LOGIN")


# ---------------------------------------------------------------------- 工具

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def append_history(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


class RunLock:
    """跨进程互斥：计划任务和手动运行撞车时，后来的直接退出。"""

    def __init__(self, path: str = LOCK_FILE, stale_seconds: float = 3 * 3600):
        self.path = path
        self.stale_seconds = stale_seconds
        self.acquired = False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
                )
                if not handle:
                    return False
                try:
                    exit_code = ctypes.c_ulong()
                    if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return exit_code.value == STILL_ACTIVE
                    return True
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return True

    def __enter__(self) -> "RunLock":
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            try:
                age = time.time() - os.path.getmtime(self.path)
            except OSError:
                age = 0
            lock_pid = 0
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    first_token = (f.read().strip().split() or [""])[0]
                    if first_token.isdigit():
                        lock_pid = int(first_token)
            except Exception:
                lock_pid = 0
            alive = self._pid_alive(lock_pid) if lock_pid else True
            if alive and age < self.stale_seconds:
                raise RuntimeError(
                    f"已有另一个每日任务在运行（PID={lock_pid or '未知'}，{self.path}，"
                    f"{age / 60:.0f} 分钟前创建）。如果确认没有在跑，删除该文件后重试。"
                )
            try:
                os.remove(self.path)
            except OSError:
                pass
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {now_iso()}\n".encode())
        os.close(fd)
        self.acquired = True
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.acquired:
            try:
                os.remove(self.path)
            except OSError:
                pass


def render_qr(image_bytes: bytes) -> None:
    """把二维码保存成 PNG，并尽量在终端画出来。"""
    path = os.path.join(ROOT, "state", "login_qr.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image_bytes)
    try:
        from zhsgo.cli import render_terminal_qr

        render_terminal_qr(image_bytes)
    except Exception:
        pass
    print(f"\n二维码已保存：{path}\n请用手机「知到」App 扫码，并在手机上确认登录。\n")


def print_status(cfg: Config) -> int:
    status = read_json(STATUS_FILE)
    budget = read_json(os.path.join(ROOT, "state", "budget.json"))
    today = datetime.now().date().isoformat()
    q = (budget.get("budget") or {}) if isinstance(budget, dict) else {}
    minutes = float(q.get("seconds", 0.0)) / 60.0 if q.get("date") == today else 0.0
    target = float(cfg.budget.daily_minutes)
    print("=" * 64)
    print(f"日期        {today}")
    print(f"今日已学    {minutes:.1f} / {target:.0f} 分钟")
    print(f"状态文件    {STATUS_FILE}")
    if status:
        print(f"最近一次    {status.get('finished_at') or status.get('started_at')}")
        print(f"结果        {status.get('result')}  {status.get('error') or ''}")
        print(f"是否完成    {'是' if status.get('all_completed') else '否'}")
    if os.path.exists(NEED_LOGIN):
        print("登录状态    需要重新扫码（state/NEED_LOGIN 存在）")
    print("=" * 64)
    return 0


# ---------------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daily",
        description="智慧树每日 25 分钟自动学习（拿满学习习惯分）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python daily.py --login\n"
            "  python daily.py\n"
            "  python daily.py --course 1919 --minutes 26\n"
            "  python daily.py --fetch\n"
            "  python daily.py --status\n"
        ),
    )
    p.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    p.add_argument("--course", nargs="+", help="只学指定课程 ID（共享课 racId / 校内课 courseId）")
    p.add_argument("--minutes", type=float, help="覆盖每日分钟数（默认读 config.yaml）")
    p.add_argument("--speed", type=float, help="覆盖播放速度（默认 1.0）")
    p.add_argument("--login", action="store_true", help="强制重新扫码登录")
    p.add_argument("--fetch", action="store_true", help="拉取课程清单后退出")
    p.add_argument("--status", action="store_true", help="查看今日状态后退出")
    p.add_argument("--no-relay", action="store_true", help="关闭验证码浏览器中继")
    p.add_argument("--dry-run", action="store_true", help="只打印配置，不连网站")
    p.add_argument("--debug", action="store_true", help="输出 DEBUG 日志")
    return p


def apply_args(cfg: Config, args: argparse.Namespace) -> None:
    if args.minutes is not None:
        if args.minutes <= 0:
            raise SystemExit("--minutes 必须大于 0")
        cfg.budget.daily_minutes = float(args.minutes)
    if args.speed is not None:
        cfg.study.speed = float(args.speed)
    if args.no_relay:
        cfg.relay.enabled = False
    if args.debug:
        cfg.log.level = "DEBUG"


def run(args: argparse.Namespace) -> int:
    stderr_safe()
    cfg = Config.load(args.config)
    apply_args(cfg, args)

    if args.status:
        return print_status(cfg)

    print("=" * 64)
    print("智慧树 · 每日学习")
    print(f"配置文件    {cfg.config_path}")
    print(f"每日目标    {cfg.budget.daily_minutes:.0f} 分钟")
    print(f"播放速度    {cfg.study.speed or cfg.pacer.default_speed}x")
    print(f"验证码中继  {'开启' if cfg.relay.enabled else '关闭'}")
    print(f"AI 弹题     {'开启 (' + cfg.ai.backend + ')' if cfg.ai.enabled else '关闭（仅用服务端答案）'}")
    print("=" * 64)
    if args.dry_run:
        print("dry-run：没有连接任何服务。")
        return 0

    target_seconds = cfg.budget.daily_minutes * 60.0
    started = now_iso()
    result = "unknown"
    error = ""
    studied = 0.0
    all_completed = False
    app = None

    try:
        with RunLock():
            with App(cfg) as app:
                # 每次 daily.py 都是一次独立运行：清掉上次进程留下的
                # session_started，避免把隔了几小时的下一次运行误判成
                # “连续在线 3 小时”，先强制休息 36 分钟。
                app.budget.close_session()
                # 今天已经学够：不再登录、不再发请求
                if app.budget.daily_seconds() >= target_seconds:
                    studied = app.budget.daily_seconds()
                    result = "already_done"
                    log().info(
                        f"今天已学 {studied / 60:.1f} 分钟，达到目标 "
                        f"{cfg.budget.daily_minutes:.0f} 分钟，直接收工。"
                    )
                    return 0

                # 登录：有 cookie 就复用；没有则要求先 --login。
                # 不在计划任务里自动弹二维码 —— 无人值守时那会一直挂到超时。
                if args.login:
                    app.login(on_qr=render_qr, force=True, qr=True)
                    try:
                        os.remove(NEED_LOGIN)
                    except OSError:
                        pass
                    result = "login"
                    log().info("登录完成，cookie 已保存；下次运行 daily.py 即可开始学习。")
                    return 0
                elif not app.passport.uuid:
                    raise AuthError(
                        "没有可用登录态。请先在交互终端运行：python daily.py --login"
                    )

                runner = StudyRunner(app)

                if args.fetch:
                    courses = runner.list_courses()
                    path = os.path.join(ROOT, "courses.json")
                    write_json(path, {"courses": courses, "fetched_at": now_iso()})
                    print(f"\n共 {len(courses)} 门课程，已写入 {path}\n")
                    for c in courses:
                        print(f"  [{c.get('type')}] {c.get('id')}  {c.get('name')}")
                    result = "fetch"
                    return 0

                try:
                    if args.course:
                        for cid in args.course:
                            runner.run_course(str(cid))
                        runner.last_course_count = len(args.course)
                    else:
                        runner.run_all()
                    # 没有触发 BudgetExhausted，且确实有课程、没有课程级错误，
                    # 才认为“全部完成”。否则只是本轮没学到东西，不能写 ALL_DONE。
                    all_completed = (
                        app.budget.daily_seconds() < 1.0
                        and runner.last_course_count > 0
                        and not runner.last_course_errors
                    )
                    if runner.last_course_errors:
                        result = "partial_error"
                        error = "; ".join(runner.last_course_errors[:3])
                    else:
                        result = "completed" if all_completed else "finished"
                except BudgetExhausted as exc:
                    result = "daily_target_reached"
                    log().warning(f"今日额度用尽，正常收工: {exc}")
                except Stopped:
                    result = "stopped"
                    log().warning("收到停止信号")

                studied = app.budget.daily_seconds()
                if all_completed:
                    try:
                        with open(os.path.join(ROOT, "state", "ALL_DONE"), "w", encoding="utf-8") as f:
                            f.write(f"{now_iso()}\n")
                    except OSError:
                        pass
                    log().info("没有未完成视频：本课程可能已经拿满。")

    except RuntimeError as exc:
        result = "locked"
        error = str(exc)
        log().error(error)
        return 5
    except AuthError as exc:
        result = "need_login"
        error = str(exc)
        try:
            os.makedirs(os.path.dirname(NEED_LOGIN), exist_ok=True)
            with open(NEED_LOGIN, "w", encoding="utf-8") as f:
                f.write(f"{now_iso()}\n{error}\n")
        except OSError:
            pass
        log().error(f"登录问题: {exc}")
        return 2
    except CaptchaRequired as exc:
        result = "captcha"
        error = str(exc)
        log().error(f"人机验证未通过: {exc}")
        return 3
    except RiskLocked as exc:
        result = "risk_locked"
        error = str(exc)
        log().error(f"风控锁定: {exc}")
        return 4
    except KeyboardInterrupt:
        result = "interrupted"
        error = "KeyboardInterrupt"
        log().warning("用户中断")
        return 130
    except ZhsError as exc:
        result = "error"
        error = str(exc)
        log().error(f"运行失败: {exc}")
        return 1
    except Exception as exc:  # 计划任务里必须留下可读原因
        result = "error"
        error = f"{type(exc).__name__}: {exc}"
        log().exception(f"未预期错误: {error}")
        return 1
    finally:
        # 失败/中断时把当天唯一的会话名额退回去，否则重试会被
        # daily_sessions=1 误判成“今天已经学够了”。
        if app is not None and result in (
            "need_login", "captcha", "risk_locked", "error",
            "partial_error", "interrupted", "stopped",
        ):
            try:
                app.budget.release_failed_session()
                app.save_state()
                studied = app.budget.daily_seconds()
            except Exception:
                pass
        status = {
            "date": datetime.now().date().isoformat(),
            "started_at": started,
            "finished_at": now_iso(),
            "target_minutes": cfg.budget.daily_minutes,
            "studied_minutes": round(studied / 60.0, 2),
            "result": result,
            "error": error,
            "all_completed": all_completed,
            "courses": args.course or [],
        }
        try:
            write_json(STATUS_FILE, status)
            append_history(status)
        except Exception:
            pass
        print(
            f"\n今日结果：{result} | 已学 {studied / 60:.1f} 分钟"
            + (f" | {error}" if error else "")
        )


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
