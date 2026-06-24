#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


COMMON_REL = Path("submodules/common")


def run(cmd, cwd=None, check=False):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def repo_root() -> Path:
    r = run(["git", "rev-parse", "--show-toplevel"])
    if r.returncode == 0:
        return Path(r.stdout.strip()).resolve()
    return Path.cwd().resolve()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[ERR] JSON 解析失败: {path}")
        sys.exit(1)


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_unique_list(data: dict, key: str, value):
    old = data.get(key)
    if old is None:
        data[key] = [value]
        return
    if not isinstance(old, list):
        data[key] = [old]
    if value not in data[key]:
        data[key].append(value)


def merge_vscode_settings(root: Path):
    vscode = root / ".vscode"
    settings_path = vscode / "settings.json"
    settings = load_json(settings_path)

    common_python = "${workspaceFolder}/submodules/common/python"

    append_unique_list(settings, "python.analysis.extraPaths", common_python)

    settings["python.envFile"] = "${workspaceFolder}/.env.common"

    settings["terminal.integrated.env.linux"] = {
        **settings.get("terminal.integrated.env.linux", {}),
        "PYTHONPATH": "${workspaceFolder}/submodules/common/python:${env:PYTHONPATH}",
    }

    settings["terminal.integrated.env.osx"] = {
        **settings.get("terminal.integrated.env.osx", {}),
        "PYTHONPATH": "${workspaceFolder}/submodules/common/python:${env:PYTHONPATH}",
    }

    settings["terminal.integrated.env.windows"] = {
        **settings.get("terminal.integrated.env.windows", {}),
        "PYTHONPATH": "${workspaceFolder}/submodules/common/python;${env:PYTHONPATH}",
    }

    settings["C_Cpp.default.compileCommands"] = (
        "${workspaceFolder}/build/compile_commands.json"
    )

    append_unique_list(
        settings,
        "clangd.arguments",
        "--compile-commands-dir=${workspaceFolder}/build",
    )

    append_unique_list(
        settings,
        "cmake.configureArgs",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    )

    settings["java.configuration.updateBuildConfiguration"] = "automatic"
    settings["rust-analyzer.cargo.allFeatures"] = True

    save_json(settings_path, settings)
    print(f"[OK] updated {settings_path.relative_to(root)}")


def write_env_common(root: Path):
    common_python = root / COMMON_REL / "python"

    paths = [
        str(root),
        str(common_python),
    ]

    env_path = root / ".env.common"
    env_path.write_text(
        "PYTHONPATH=" + os.pathsep.join(paths) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] written {env_path.relative_to(root)}")


def update_gitignore(root: Path):
    gitignore = root / ".gitignore"
    line = ".env.common"

    if gitignore.exists():
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    if line not in lines:
        lines.append(line)
        gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("[OK] updated .gitignore")
    else:
        print("[OK] .gitignore already contains .env.common")


def update_go_work(root: Path):
    root_go_mod = root / "go.mod"
    common_go_mod = root / COMMON_REL / "golang/go.mod"

    if not root_go_mod.exists():
        print("[SKIP] root go.mod not found")
        return

    if not common_go_mod.exists():
        print("[SKIP] common golang/go.mod not found")
        return

    if not (root / "go.work").exists():
        r = run(["go", "work", "init", "."], cwd=root)
        if r.returncode != 0:
            print("[WARN] go work init failed")
            print(r.stderr.strip())
            return

    r = run(["go", "work", "use", ".", "./submodules/common/golang"], cwd=root)
    if r.returncode != 0:
        print("[WARN] go work use failed")
        print(r.stderr.strip())
        return

    print("[OK] updated go.work")


def file_contains(path: Path, text: str) -> bool:
    if not path.exists():
        return False
    try:
        return text in path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def exists_mark(path: Path) -> str:
    return "OK" if path.exists() else "MISS"


def doctor(root: Path):
    common = root / COMMON_REL

    checks = []

    checks.append(("common root", common))
    checks.append(("common/python", common / "python"))
    checks.append(("common/cpp", common / "cpp"))
    checks.append(("common/golang", common / "golang"))
    checks.append(("common/rust", common / "rust"))
    checks.append(("common/java", common / "java"))
    checks.append(("common/dotnet", common / "dotnet"))

    print("\n== Path checks ==")
    for name, path in checks:
        print(f"{exists_mark(path):4} {name:18} {path.relative_to(root)}")

    print("\n== Config checks ==")

    settings = root / ".vscode/settings.json"
    env_common = root / ".env.common"
    compile_commands = root / "build/compile_commands.json"
    go_work = root / "go.work"
    root_cargo = root / "Cargo.toml"

    print(f"{exists_mark(settings):4} VSCode settings      .vscode/settings.json")
    print(f"{exists_mark(env_common):4} Python env          .env.common")
    print(f"{exists_mark(compile_commands):4} C++ compile db      build/compile_commands.json")
    print(f"{exists_mark(go_work):4} Go workspace        go.work")

    if settings.exists():
        s = settings.read_text(encoding="utf-8", errors="ignore")
        print(
            f"{'OK' if 'submodules/common/python' in s else 'MISS':4} "
            "VSCode Python path"
        )
        print(
            f"{'OK' if 'compile_commands.json' in s else 'MISS':4} "
            "VSCode C++ compileCommands"
        )

    if go_work.exists():
        print(
            f"{'OK' if 'submodules/common/golang' in go_work.read_text(encoding='utf-8', errors='ignore') else 'MISS':4} "
            "Go common module"
        )

    if root_cargo.exists():
        print(
            f"{'OK' if file_contains(root_cargo, 'submodules/common/rust') else 'MISS':4} "
            "Rust path dependency"
        )
    else:
        print("SKIP Rust root Cargo.toml not found")

    print("\n== Next commands ==")
    print("C++ 生成 compile_commands.json:")
    print("  cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    print()
    print("Python 检查 import 路径:")
    print("  python -c 'import sys; print(\"\\n\".join(sys.path[:5]))'")
    print()
    print("Go 检查 workspace:")
    print("  go env GOWORK")


def apply(root: Path, with_go: bool):
    common = root / COMMON_REL

    if not common.exists():
        print(f"[ERR] missing {COMMON_REL}")
        print("你可能需要先执行:")
        print("  git submodule update --init --recursive")
        sys.exit(1)

    merge_vscode_settings(root)
    write_env_common(root)
    update_gitignore(root)

    if with_go:
        update_go_work(root)

    print("\n[DONE] common config synced")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["apply", "doctor"])
    parser.add_argument(
        "--go",
        action="store_true",
        help="apply 时顺便维护 go.work",
    )

    args = parser.parse_args()
    root = repo_root()

    if args.cmd == "apply":
        apply(root, with_go=args.go)
    elif args.cmd == "doctor":
        doctor(root)


if __name__ == "__main__":
    main()