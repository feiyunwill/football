#!/usr/bin/env python3
"""Build native-only binaries, inspect ELF dependencies, and relocate the binding."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
# 2026-09-24: include the actual recoverable UDP products in the native-only gate.
# TARGETS = ("football_server", "football_client", "football_server_tcp", "football_client_tcp",
#            "football_lobby", "headless_match", "standalone_game")

TARGETS = ("football_server", "football_client", "football_server_tcp", "football_client_tcp",
           "football_server_udp", "football_client_udp", "football_lobby", "headless_match", "standalone_game")


# 2026-09-10: relocation checks must control the loader environment explicitly.
# def run(argv, capture=False, cwd=ROOT):
def run(argv, capture=False, cwd=ROOT, env=None):
    print("Running: " + " ".join(map(str, argv)), flush=True)
    return subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None).stdout


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("/tmp/football-optimization-native"))
    args = parser.parse_args()
    build = args.build.resolve()
    require(platform.system() == "Linux", "ELF acceptance must run on the Linux target")
    run(["cmake", "-S", "engine", "-B", build, "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_PYTHON_BINDINGS=OFF",
         f"-DFOOTBALL_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}"])
    commands = json.loads((build / "compile_commands.json").read_text())
    require(not any(Path(command["file"]).name == "ai.cpp" for command in commands),
            "Native-only configuration still compiles the Python adapter")
    require(not any("pybind11" in command["command"] or "include/python" in command["command"]
                    for command in commands), "Native compiler commands still depend on Python headers")
    run(["cmake", "--build", build, "-j", "1", "--target", *TARGETS])
    dependencies = {}
    for target in TARGETS + ("libfootball_engine.so",):
        binary = build / (target if target.endswith(".so") else f"bin/{target}")
        dynamic = run(["readelf", "-d", binary], capture=True)
        needed = re.findall(r"\(NEEDED\).*\[([^\]]+)\]", dynamic)
        require(not any("python" in library.lower() or library.startswith("libgame.") for library in needed),
                f"{target} links a Python/binding runtime: {needed}")
        dependencies[target] = needed
    symbols = run(["nm", "-D", "--undefined-only", build / "libfootball_engine.so"], capture=True)
    require(not re.search(r"\b_?Py[A-Za-z_]", symbols), "Native engine has undefined Python API references")
    # A second configure enables only the adapter; the native engine is reused.
    # 2026-09-10: use this gate's Python and installed pybind11; never fetch Git.
    # run(["cmake", "-S", "engine", "-B", build, "-DBUILD_PYTHON_BINDINGS=ON"])
    import pybind11
    run(["cmake", "-S", "engine", "-B", build, "-DBUILD_PYTHON_BINDINGS=ON",
         f"-DPython_EXECUTABLE={sys.executable}", f"-DPython_ROOT_DIR={sys.prefix}",
         f"-Dpybind11_DIR={pybind11.get_cmake_dir()}"])
    run(["cmake", "--build", build, "-j", "1", "--target", "game"])
    with tempfile.TemporaryDirectory(prefix="football-relocated-binding-") as directory:
        # 2026-09-10: the old AST probe targeted retired setup.py methods.
        # Verify the real package loader and actual mapped sibling library.
        # staging = Path(directory) / "staging"
        # relocated = Path(directory) / "relocated"
        # (staging / "engine").mkdir(parents=True)
        # relocated.mkdir()
        # shutil.copy2(build / "libgame.so", staging / "engine/_gameplayfootball.so")
        # shutil.copy2(build / "libfootball_engine.so", staging / "engine/libfootball_engine.so")
        # # Evaluate only the actual Unix library selection and copying function,
        # # without running setuptools or installing the package into the host.
        # packaging_probe = """
        # import ast, glob, pathlib, shutil, sys
        # tree = ast.parse(pathlib.Path(sys.argv[1]).read_text())
        # cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'CustomBuild')
        # method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_unix')
        # selection = next(n for n in ast.walk(method) if isinstance(n, ast.Assign) and
        # any(isinstance(t, ast.Name) and t.id == 'libs' for t in n.targets))
        # copier = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'copy_compiled_libs')
        # namespace = {'shutil': shutil}
        # exec(compile(ast.Module(body=[copier], type_ignores=[]), 'setup.py', 'exec'), namespace)
        # libraries = eval(compile(ast.Expression(selection.value), 'setup.py', 'eval'), {'glob': glob})
        # assert len(libraries) == 2, libraries
        # namespace['copy_compiled_libs'](libraries, sys.argv[2])
        # """
        # run([sys.executable, "-I", "-c", packaging_probe, ROOT / "setup.py", relocated], cwd=staging)
        # # Load from an unrelated cwd and use the real setup.py library copier.
        # # The module must find its sibling engine through $ORIGIN, without an
        # # LD_LIBRARY_PATH adjustment or the original build directory.
        # probe = (
        # "import importlib.util, pathlib; "
        # "p=pathlib.Path('_gameplayfootball.so').resolve(); "
        # "s=importlib.util.spec_from_file_location('_gameplayfootball',p); "
        # "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        # "assert hasattr(m,'GameEnv'); e=m.GameEnv(); assert hasattr(e,'step')"
        # )
        # run([sys.executable, "-I", "-c", probe], cwd=relocated)

        relocated = Path(directory) / "relocated"
        package = relocated / "gfootball_engine"
        package.mkdir(parents=True)
        shutil.copy2(build / "libgame.so", package / "_gameplayfootball.so")
        shutil.copy2(build / "libfootball_engine.so", package / "libfootball_engine.so")
        shutil.copy2(ROOT / "engine/__init__.py", package / "__init__.py")
        environment = dict(os.environ)
        environment.pop("LD_LIBRARY_PATH", None)
        environment.pop("LD_PRELOAD", None)
        environment.pop("PYTHONPATH", None)
        probe = """
import importlib, json, pathlib, pickle, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
before = list(sys.path)
import gfootball_engine
module = importlib.import_module('gfootball_engine._gameplayfootball')
assert pathlib.Path(module.__file__).resolve().parent == root/'gfootball_engine'
assert sys.path == before
assert sys.modules['_gameplayfootball'] is module
assert gfootball_engine.GameEnv is module.GameEnv
role = module.e_PlayerRole.e_PlayerRole_GK
assert pickle.loads(pickle.dumps(role)) == role
env = module.GameEnv()
assert callable(env.step)
mapped = {pathlib.Path(line.split()[-1]).resolve()
          for line in pathlib.Path('/proc/self/maps').read_text().splitlines()
          if line.split()[-1].endswith('/libfootball_engine.so')}
assert mapped == {root/'gfootball_engine/libfootball_engine.so'}, mapped
print(json.dumps(dict(passed=True, assertions=7, mapped_engine=[str(p) for p in mapped])))
"""
        output = run([sys.executable, "-I", "-c", probe, relocated], capture=True,
                     cwd=Path(directory), env=environment)
        relocation = json.loads(output.strip().splitlines()[-1])
        require(relocation.get("passed") is True and relocation.get("assertions") == 7,
                "Relocated package contract incomplete")
    print(json.dumps({"passed": True, "assertions": len(dependencies) + 4, "skipped": 0,
                      "platform": platform.platform(), "dependencies": dependencies,
                      "relocated_python_import": True, "relocated_package": relocation,
                      "binding_python": sys.executable, "pybind11": pybind11.__version__,
                      "packaging_scope": "native relocation; actual wheel installation has a separate probe",
                      "build": str(build)}))


if __name__ == "__main__":
    main()
