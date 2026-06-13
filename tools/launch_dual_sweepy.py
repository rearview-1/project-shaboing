import argparse
import os
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Launch two Sweepy backend instances with isolated runtimes and shared learning roots.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for both instances.")
    parser.add_argument("--instance-a", default="account_a", help="Instance label for the first backend.")
    parser.add_argument("--instance-b", default="account_b", help="Instance label for the second backend.")
    parser.add_argument("--port-a", type=int, default=1616, help="Port for the first backend.")
    parser.add_argument("--port-b", type=int, default=1717, help="Port for the second backend.")
    parser.add_argument("--python", default=sys.executable or "python", help="Python interpreter to use.")
    return parser.parse_args()


def launch_instance(repo_root, python_exe, *, host, port, instance_name, runtime_dir, shared_runtime_paths):
    main_script = repo_root / "main.py"
    env = os.environ.copy()
    env["SWEEPY_HOST"] = str(host)
    env["SWEEPY_PORT"] = str(port)
    env["SWEEPY_INSTANCE_NAME"] = str(instance_name)
    env["UMA_RUNTIME_DIR"] = str(runtime_dir)
    env["SWEEPY_SHARED_RUNTIME_PATHS"] = os.pathsep.join(str(path) for path in shared_runtime_paths)
    env["SWEEPY_AUTO_LEARNING_SCOPE"] = "instance_local"
    env["SWEEPY_AUTH_CAPTURE_KILL_GAME"] = "0"
    env["SWEEPY_INSTANCE_DEVICE_IDENTITY"] = "1"
    env["SWEEPY_STEAM_APP_ID"] = "3224770"
    env["SWEEPY_GAME_PROCESS_NAME"] = "UmamusumePrettyDerby.exe"
    env.setdefault("SWEEPY_PROJECT_ROOT", str(repo_root))
    env.setdefault("SWEEPY_RESTART_SCRIPT", str(main_script))
    env.setdefault("SWEEPY_RESTART_PYTHON", str(python_exe))
    env.setdefault("SWEEPY_AUTO_GIT_UPDATE", "1")
    env.setdefault("SWEEPY_AUTO_GIT_UPDATE_INITIAL_DELAY_SEC", "0")

    cmd = [python_exe, str(main_script)]
    kwargs = {
        "cwd": str(repo_root),
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    return subprocess.Popen(cmd, **kwargs)


def main():
    args = parse_args()
    if args.port_a == args.port_b:
        raise SystemExit("Dual launch requires two different ports.")

    repo_root = Path(__file__).resolve().parents[1]
    runtime_base = repo_root / "uma_runtime" / "instances"
    runtime_a = runtime_base / args.instance_a
    runtime_b = runtime_base / args.instance_b
    runtime_a.mkdir(parents=True, exist_ok=True)
    runtime_b.mkdir(parents=True, exist_ok=True)

    shared_runtime_paths = [runtime_a, runtime_b]
    proc_a = launch_instance(
        repo_root,
        args.python,
        host=args.host,
        port=args.port_a,
        instance_name=args.instance_a,
        runtime_dir=runtime_a,
        shared_runtime_paths=shared_runtime_paths,
    )
    proc_b = launch_instance(
        repo_root,
        args.python,
        host=args.host,
        port=args.port_b,
        instance_name=args.instance_b,
        runtime_dir=runtime_b,
        shared_runtime_paths=shared_runtime_paths,
    )

    print(f"Started {args.instance_a} on http://{args.host}:{args.port_a} (pid={proc_a.pid})")
    print(f"Started {args.instance_b} on http://{args.host}:{args.port_b} (pid={proc_b.pid})")
    print(f"Shared runtime roots: {runtime_a} ; {runtime_b}")


if __name__ == "__main__":
    main()
