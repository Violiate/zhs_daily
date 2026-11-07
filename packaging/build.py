#!/usr/bin/env python3
"""一键打包 zhs_daily 为免安装 Windows 可执行程序与开箱即用压缩包。

用法：
    python packaging/build.py release       # 同时构建完整版 (full) 与轻量版 (lite) 并打 zip
    python packaging/build.py full          # 只构建完整版 zhs-daily.exe + zip
    python packaging/build.py lite          # 只构建轻量版 zhs-daily-lite.exe + zip

构建完成后会自动在临时隔离目录中运行 `--dry-run`、`--all --dry-run` 与 `--selfcheck`
自检，确保打包出的 exe 真正可运行、依赖无缺失。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "zhs-daily.spec")
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build")

VARIANT_DEPS = {
    "full": ["playwright", "ddddocr", "cv2", "onnxruntime", "numpy", "PIL"],
    "lite": ["PIL"],
}


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def exe_name(variant: str) -> str:
    return "zhs-daily" if variant == "full" else "zhs-daily-lite"


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def dir_size(path: str) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


def check_env(variant: str) -> List[str]:
    problems: List[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problems.append("未安装 PyInstaller：pip install pyinstaller")
    for mod in VARIANT_DEPS.get(variant, []):
        try:
            __import__(mod)
        except ImportError:
            problems.append(f"{variant} 版需要 {mod}：pip install -r requirements.txt")
    return problems


def kill_stale(name: str) -> int:
    if sys.platform != "win32":
        return 0
    try:
        proc = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", f"{name}.exe"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            print(f"  （已清理残留的 {name}.exe 进程）")
            return 1
    except Exception:
        pass
    return 0


def build_one(variant: str, onefile: bool) -> Tuple[str, float]:
    name = exe_name(variant)
    kill_stale(name)

    env = os.environ.copy()
    env["ZHS_VARIANT"] = variant
    env["ZHS_ONEFILE"] = "1" if onefile else "0"

    label = f"{name}.exe ({'完整版·含自动过验证码' if variant == 'full' else '轻量版'}，{'单文件' if onefile else '目录'})"
    print(f"\n{'=' * 68}")
    print(f"构建 {label}")
    print(f"{'=' * 68}")

    t0 = time.time()
    # 兼容 Python 3.12+ 下旧版 setuptools/pkg_resources 在主进程或 PyInstaller 子进程中
    # 访问已移除的 pkgutil.ImpImporter
    os.makedirs(WORK, exist_ok=True)
    sitecust = os.path.join(WORK, "sitecustomize.py")
    with open(sitecust, "w", encoding="utf-8") as f:
        f.write(
            "import pkgutil, zipimport\n"
            "if not hasattr(pkgutil, 'ImpImporter'):\n"
            "    pkgutil.ImpImporter = zipimport.zipimporter\n"
        )
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{WORK}{os.pathsep}{old_pp}" if old_pp else WORK

    proc = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--log-level", "WARN", "--distpath", DIST, "--workpath", WORK, SPEC],
        env=env, cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"[!] PyInstaller 构建失败，退出码 {proc.returncode}")

    target = os.path.join(DIST, f"{name}.exe" if onefile else name)
    if not os.path.exists(target):
        raise SystemExit(f"[!] 没找到构建产物: {target}")

    size = os.path.getsize(target) if onefile else dir_size(target)
    print(f"构建完成，用时 {time.time() - t0:.0f}s，体积 {human(size)}")
    return target, size


def _test_cli_run(exe: str, cwd: str, args: list, marker: str) -> bool:
    print(f"\n自检 {os.path.basename(exe)} ({' '.join(args)}) ...")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe] + args, cwd=cwd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0 and marker in out
        print(f"  退出码 {proc.returncode}，用时 {time.time() - t0:.1f}s")
        for line in out.strip().splitlines()[:12]:
            print(f"  | {line}")
        print("  [ok] 自检通过" if ok else "  [!!] 自检失败（见上方输出）")
        return ok
    except subprocess.TimeoutExpired:
        print("  [!!] 自检超时")
        return False
    except Exception as e:
        print(f"  [!!] 自检异常: {e}")
        return False


def self_test(variant: str, onefile: bool) -> bool:
    name = exe_name(variant)
    exe = os.path.join(DIST, f"{name}.exe") if onefile else os.path.join(DIST, name, f"{name}.exe")
    if not os.path.exists(exe):
        print(f"  [!!] 找不到 {exe}")
        return False

    tmp = tempfile.mkdtemp(prefix="zhs-daily-selftest-")
    try:
        ok1 = _test_cli_run(exe, tmp, ["--dry-run"], "dry-run")
        ok2 = _test_cli_run(exe, tmp, ["--all", "--dry-run"], "一口气刷完模式")
        ok3 = _test_cli_run(exe, tmp, ["--selfcheck"], "自检通过")
        return ok1 and ok2 and ok3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for junk in ("config.yaml", "state", "logs", "courses.json"):
            p = os.path.join(DIST, junk)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.exists(p):
                os.remove(p)


def make_zip(variant: str, onefile: bool) -> str:
    """将 exe 与一键启动脚本 (.bat / .ps1)、示例配置、说明文档打包成开箱即用的 zip。"""
    name = exe_name(variant)
    src = os.path.join(DIST, f"{name}.exe") if onefile else os.path.join(DIST, name)
    out = os.path.join(DIST, f"{name}-windows-x64.zip")

    print(f"\n生成开箱即用发布包 {os.path.basename(out)} ...")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if onefile:
            z.write(src, f"{name}.exe")
        else:
            for base, _dirs, files in os.walk(src):
                for f in files:
                    full = os.path.join(base, f)
                    rel = os.path.relpath(full, src)
                    z.write(full, os.path.join(name, rel))
        for extra, arc in (
            ("run_login.bat", "run_login.bat"),
            ("run_daily.bat", "run_daily.bat"),
            ("run_all.bat", "run_all.bat"),
            ("install_task.ps1", "install_task.ps1"),
            ("config.example.yaml", "config.example.yaml"),
            ("README.md", "README.md"),
            ("DISCLAIMER.md", "DISCLAIMER.md"),
            ("LICENSE", "LICENSE"),
        ):
            path = os.path.join(ROOT, extra)
            if os.path.exists(path):
                z.write(path, arc)

    size = os.path.getsize(out)
    print(f"  [ok] {out}  ({human(size)})")
    return out


def main() -> int:
    _force_utf8()
    ap = argparse.ArgumentParser(prog="packaging/build.py")
    ap.add_argument("variant", nargs="?", default="release",
                    choices=["full", "lite", "release"],
                    help="full=完整版，lite=轻量版，release=同时构建两个版本（默认）")
    ap.add_argument("--dir", action="store_true", help="输出目录形态而非单文件 exe")
    ap.add_argument("--no-zip", action="store_true", help="不生成 zip 发布包")
    ap.add_argument("--no-test", action="store_true", help="跳过打包后自检")
    ns = ap.parse_args()

    targets = ["full", "lite"] if ns.variant == "release" else [ns.variant]
    onefile = not ns.dir

    for variant in targets:
        problems = check_env(variant)
        if problems:
            print(f"[!] {variant} 版构建环境不满足：")
            for p in problems:
                print(f"    - {p}")
            return 1

    results = []
    for variant in targets:
        target, size = build_one(variant, onefile)
        ok = True if ns.no_test else self_test(variant, onefile)
        results.append((exe_name(variant), target, size, ok))
        if not ns.no_zip and ok:
            make_zip(variant, onefile)

    print(f"\n{'=' * 68}")
    print("构建汇总")
    print(f"{'=' * 68}")
    for name, target, size, ok in results:
        print(f"  [{'OK' if ok else '!!'}] {os.path.relpath(target, ROOT):40} {human(size)}")
    return 0 if all(r[3] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
