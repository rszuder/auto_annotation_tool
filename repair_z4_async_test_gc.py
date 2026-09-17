#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# repair_z4_async_test_gc.py
#
# Minimalna stabilizacja pełnego unittest suite dla Tk/Tcl.
#
# Zmienia WYŁĄCZNIE:
#   tests/test_z4_async_training_preflight.py
#
# Uruchom:
#   python repair_z4_async_test_gc.py
#   python repair_z4_async_test_gc.py --test
#   python repair_z4_async_test_gc.py --test --full

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TARGET = Path("tests/test_z4_async_training_preflight.py")


def atomic_write(path, text):
    tmp = path.with_name("." + path.name + ".gcfix.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: oczekiwano dokładnie 1 kotwicy, znaleziono {count}."
        )
    return text.replace(old, new, 1)


def patch_file(text):
    changes = []

    # 1. import gc
    if "\nimport gc\n" not in text and not text.startswith("import gc\n"):
        text = replace_once(
            text,
            "import tempfile\n",
            "import gc\nimport tempfile\n",
            "import gc",
        )
        changes.append("dodano import gc")

    # 2. GC na main thread przed utworzeniem hosta/Tcl fixture.
    marker = "gc.collect()  # collect Tk/Tcl objects on the main test thread"
    if marker not in text:
        old = (
            "        self.dataset.mkdir()\n"
            "        (self.dataset / \"data.yaml\").write_text(\n"
        )
        new = (
            "        self.dataset.mkdir()\n"
            "        gc.collect()  # collect Tk/Tcl objects on the main test thread\n"
            "        (self.dataset / \"data.yaml\").write_text(\n"
        )
        text = replace_once(text, old, new, "gc.collect w setUp")
        changes.append("dodano gc.collect() w setUp")

    # 3. Nie używaj Mock jako cleanup wykonywanego w worker thread.
    if '("cleanup_gpu_memory", lambda: None),' not in text:
        old = '            ("cleanup_gpu_memory", Mock()),\n'
        new = (
            "            # Plain callable: avoid unittest.mock becoming the place where GC\n"
            "            # collects old Tk/Tcl objects inside Z4TrainingPreflight worker.\n"
            '            ("cleanup_gpu_memory", lambda: None),\n'
        )
        text = replace_once(text, old, new, "cleanup_gpu_memory patch")
        changes.append("zamieniono cleanup_gpu_memory Mock() na lambda")

    return text, changes


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    target = repo / TARGET

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} nie jest katalogiem głównym repo Git.", file=sys.stderr)
        return 2
    if not target.is_file():
        print(f"ERROR: brak pliku {TARGET}", file=sys.stderr)
        return 2

    original = target.read_text(encoding="utf-8")

    try:
        patched, changes = patch_file(original)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if patched != original:
        atomic_write(target, patched)
        print(f"PATCHED: {TARGET}")
        for item in changes:
            print(f"  - {item}")
    else:
        print("Patch już jest zastosowany; brak zmian.")

    print("\n--- git diff -- tests/test_z4_async_training_preflight.py ---")
    run(["git", "diff", "--", str(TARGET)], repo)

    print("\nCHECK: git diff --check")
    result = run(["git", "diff", "--check"], repo)
    if result.returncode:
        return result.returncode

    if args.test or args.full:
        print("\nTEST: test_z4_async_training_preflight.py")
        result = run([
            sys.executable,
            "-X", "faulthandler",
            "-m", "unittest", "discover",
            "-s", "tests",
            "-p", "test_z4_async_training_preflight.py",
            "-v",
        ], repo)
        if result.returncode:
            return result.returncode

    if args.full:
        print("\nFULL SUITE")
        return run([
            sys.executable,
            "-X", "faulthandler",
            "-m", "unittest", "discover",
            "-s", "tests",
            "-p", "test_*.py",
            "-v",
        ], repo).returncode

    print(
        "\nGotowe. UI i runtime nie zostały zmienione.\n"
        "Teraz uruchom:\n"
        "  python repair_z4_async_test_gc.py --test\n"
        "a następnie pełny suite.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
