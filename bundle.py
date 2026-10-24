#!/usr/bin/env python3

import os
import sys
import shutil
import zipfile
import tarfile
import subprocess
import argparse
from pathlib import Path
from typing import List, Tuple


PLUGIN_NAME = "DeckyNews"

LOADER_PYTHONS = ["314"]
BUILD_DIR = Path("build")
BUNDLE_DIR = BUILD_DIR / PLUGIN_NAME
PY_MODULES_DIR = BUNDLE_DIR / "py_modules"
ZIP_NAME = f"{PLUGIN_NAME}.zip"


PLUGIN_FILES = [
    "main.py",
    "plugin.json",
    "package.json",
    "LICENSE",
    "README.md",
]


PLUGIN_DIRS = [
    ("dist", "dist"),
    ("assets", "assets"),
    ("defaults", "defaults"),
    ("bin", "bin"),
    ("src", "src"),
]


def print_step(step: int, total: int, message: str):
    print(f"\n[{step}/{total}] {message}")


def print_ok(message: str):
    print(f"  [OK] {message}")


def print_warn(message: str):
    print(f"  [WARN] {message}")


def print_error(message: str):
    print(f"  [ERROR] {message}")


def run_command(cmd: List[str], check: bool = True) -> Tuple[bool, str]:
    try:

        use_shell = sys.platform == "win32"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            shell=use_shell
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout + e.stderr
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"


def clean_build():
    print("Cleaning build directories...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"  Removed {BUILD_DIR}/")

    if Path(ZIP_NAME).exists():
        Path(ZIP_NAME).unlink()
        print(f"  Removed {ZIP_NAME}")


def build_frontend() -> bool:
    print_step(2, 7, "Building frontend with Rollup...")


    success, output = run_command(["pnpm", "run", "build"], check=False)
    if success:
        print_ok("Frontend built with pnpm")
        return True


    print_warn("pnpm not found, trying npm...")
    success, output = run_command(["npm", "run", "build"], check=False)
    if success:
        print_ok("Frontend built with npm")
        return True

    print_error("Frontend build failed")
    print(output)
    return False


def copy_plugin_files() -> bool:
    print_step(3, 7, "Copying plugin files...")


    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)


    for file_name in PLUGIN_FILES:
        src = Path(file_name)
        if src.exists():
            shutil.copy2(src, BUNDLE_DIR / file_name)
            print_ok(f"Copied {file_name}")
        else:
            if file_name in ["main.py", "plugin.json"]:
                print_error(f"Required file missing: {file_name}")
                return False
            print_warn(f"Optional file missing: {file_name}")


    for src_name, dst_name in PLUGIN_DIRS:
        src = Path(src_name)
        dst = BUNDLE_DIR / dst_name
        if src.exists():


            ignore = shutil.ignore_patterns('*.ts', '*.tsx', 'components') if src_name == "src" else None
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
            print_ok(f"Copied {src_name}/ -> {dst_name}/")

            if dst.name == "bin":
                intel_patterns = [
                    "libggml-cpu-alderlake.so",
                    "libggml-cpu-cannonlake.so",
                    "libggml-cpu-cascadelake.so",
                    "libggml-cpu-cooperlake.so",
                    "libggml-cpu-haswell.so",
                    "libggml-cpu-icelake.so",
                    "libggml-cpu-ivybridge.so",
                    "libggml-cpu-sandybridge.so",
                    "libggml-cpu-sapphirerapids.so",
                    "libggml-cpu-skylakex.so",
                    "libggml-cpu-sse42.so",
                ]

                removed_count = 0
                for pattern in intel_patterns:
                    intel_lib = dst / pattern
                    if intel_lib.exists():
                        intel_lib.unlink()
                        removed_count += 1

                if removed_count > 0:
                    print_ok(f"Removed {removed_count} Intel-specific CPU libraries (AMD Zen 2 incompatible)")


                amd_libs = ["libggml-cpu-zen4.so", "libggml-cpu-x64.so", "libggml-cpu-piledriver.so"]
                kept_count = sum(1 for lib in amd_libs if (dst / lib).exists())
                if kept_count > 0:
                    print_ok(f"Kept {kept_count} AMD-compatible CPU libraries")
        else:
            if src_name == "dist":
                print_error("dist/ directory not found. Frontend build may have failed.")
                return False
            print_warn(f"Optional directory missing: {src_name}/")

    return True


def install_python_deps(skip_llm: bool = False) -> bool:
    print_step(4, 7, "Bundling Python dependencies for Linux...")


    PY_MODULES_DIR.mkdir(parents=True, exist_ok=True)


    c_extension_deps = [
        "lxml",
        "psutil",
        "Levenshtein",
        "rapidfuzz",
        "aiohttp",
        "multidict",
        "yarl",
        "frozenlist",
        "propcache",
        "charset-normalizer",
    ]


    pure_python_deps = [
        "feedparser",
        "sgmllib3k",
        "certifi",
        "attrs",
        "idna",
        "cloudscraper",
        "readability-lxml",
        "lxml-html-clean",
        "cssselect",
        "chardet",
        "requests",
        "requests_toolbelt",
        "pyparsing",
        "urllib3",
        "aiosignal",
        "aiohappyeyeballs",
        "typing_extensions",
    ]

    print(f"  Downloading C-extension wheels (Linux x86_64, cp{', cp'.join(LOADER_PYTHONS)})...")
    for pyver in LOADER_PYTHONS:
        cmd_binary = [
            sys.executable, "-m", "pip", "download",
            "--dest", str(PY_MODULES_DIR),
            "--platform", "manylinux_2_17_x86_64",
            "--platform", "manylinux_2_28_x86_64",
            "--platform", "manylinux2014_x86_64",
            "--python-version", pyver,
            "--only-binary", ":all:",
            "--no-deps",
        ] + c_extension_deps

        success, output = run_command(cmd_binary, check=False)
        if not success:
            print_error(f"Failed to download Linux x86_64 C-extension wheels for cp{pyver}.")
            print_error(f"pip output:\n{output[-2000:]}")
            return False

    print("  Downloading pure-Python packages...")
    cmd_pure = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(PY_MODULES_DIR),
    ] + pure_python_deps

    success, output = run_command(cmd_pure, check=False)
    if not success:
        print_error("Failed to download pure-Python packages.")
        print_error(f"pip output:\n{output[-2000:]}")
        return False


    downloaded_files = list(PY_MODULES_DIR.glob("*"))
    print_ok(f"Downloaded {len(downloaded_files)} files (packages + transitive dependencies)")


    print("  Verifying critical packages and transitive dependencies...")
    critical_checks = {
        "feedparser": "feedparser",
        "Levenshtein": "Levenshtein",
        "rapidfuzz": "rapidfuzz",
        "lxml": "lxml",
        "cssselect": "cssselect",
        "chardet": "chardet",
        "certifi": "certifi",
        "psutil": "psutil",
        "aiohttp": "aiohttp",
        "cloudscraper": "cloudscraper",
        "readability": "readability",
    }

    missing_critical = []
    for pkg_name, file_prefix in critical_checks.items():
        variants = [file_prefix, file_prefix.replace("_", "-"), file_prefix.replace("-", "_")]
        if not any(v.lower() in f.name.lower() for v in variants for f in downloaded_files):
            missing_critical.append(pkg_name)

    if missing_critical:
        print_error(f"CRITICAL: Missing packages (including transitive deps): {', '.join(missing_critical)}")
        print_error("These WILL cause ModuleNotFoundError on Steam Deck!")
        print_error("Tip: Try running 'python copy_deps.py' first if you have packages installed locally.")
        return False

    print_ok(f"Verified {len(critical_checks)} critical packages (including transitive dependencies)")



    extracted_count = 0
    for wheel in PY_MODULES_DIR.glob("*.whl"):
        try:
            with zipfile.ZipFile(wheel, 'r') as whl:
                whl.extractall(PY_MODULES_DIR)
            wheel.unlink()
            extracted_count += 1
        except Exception as e:
            print_warn(f"Failed to extract {wheel.name}: {e}")


    for tarball in PY_MODULES_DIR.glob("*.tar.gz"):
        try:
            with tarfile.open(tarball, 'r:gz') as tar:

                members = tar.getmembers()
                for member in members:

                    if member.name.endswith('.py'):

                        parts = member.name.split('/', 1)
                        if len(parts) > 1:
                            member.name = parts[1]
                            tar.extract(member, PY_MODULES_DIR)
            tarball.unlink()
            extracted_count += 1
            print_ok(f"Extracted {tarball.name}")
        except Exception as e:
            print_warn(f"Failed to extract {tarball.name}: {e}")

    if extracted_count > 0:
        print_ok(f"Extracted {extracted_count} wheel files")


    for pattern in ["__pycache__", "*.pyc", "*.pyd"]:
        for item in PY_MODULES_DIR.rglob(pattern):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()


    core_present = []
    for dep in ["feedparser", "certifi"]:
        if (PY_MODULES_DIR / dep).exists() or list(PY_MODULES_DIR.glob(f"{dep}*")):
            core_present.append(dep)

    if len(core_present) >= 2:
        print_ok(f"Core dependencies bundled: {', '.join(core_present)}")
        return True
    else:
        print_warn("Some core dependencies may be missing. Bundle may need to install on device.")
        return True


def create_zip_bundle() -> bool:
    print_step(6, 7, "Creating plugin bundle...")

    if Path(ZIP_NAME).exists():
        Path(ZIP_NAME).unlink()

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(BUNDLE_DIR):

            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for file in files:

                if file.endswith('.pyc'):
                    continue

                file_path = Path(root) / file


                arcname = file_path.relative_to(BUILD_DIR).as_posix()


                info = zipfile.ZipInfo(arcname)
                info.compress_type = zipfile.ZIP_DEFLATED


                if '/bin/' in arcname or arcname.endswith('/bin'):
                    info.external_attr = (0o755 << 16) | 0x8000
                else:
                    info.external_attr = (0o644 << 16) | 0x8000

                with open(file_path, 'rb') as f:
                    zf.writestr(info, f.read())

                file_count += 1
                total_size += file_path.stat().st_size

    print_ok(f"Created {ZIP_NAME} with {file_count} files")
    return True


def validate_bundle() -> bool:
    print_step(7, 7, "Validating bundle...")

    if not Path(ZIP_NAME).exists():
        print_error("ZIP file not created")
        return False

    zip_size = Path(ZIP_NAME).stat().st_size

    with zipfile.ZipFile(ZIP_NAME, 'r') as zf:
        names = zf.namelist()


        required = [
            f"{PLUGIN_NAME}/main.py",
            f"{PLUGIN_NAME}/plugin.json",
            f"{PLUGIN_NAME}/dist/index.js",
        ]

        missing = [f for f in required if f not in names]
        if missing:
            print_error(f"Missing required files in bundle: {missing}")
            return False


        backslash_paths = [n for n in names if '\\' in n]
        if backslash_paths:
            print_error(f"Bundle contains backslashes (incompatible): {backslash_paths[:3]}")
            return False


        llamafile_binary = f"{PLUGIN_NAME}/bin/llamafile"
        legacy_binary = f"{PLUGIN_NAME}/bin/llama-cli"

        if llamafile_binary in names or legacy_binary in names:
            print_ok("AI engine binary bundled")
        else:
            print_warn("No AI binaries found - AI summarization unavailable")

        print_ok(f"Bundle validated: {len(names)} entries, {zip_size:,} bytes")
        max_size_mb = 20


        size_without_llamafile = zip_size
        for name in names:
            if 'llamafile' in name and name.endswith(('llamafile', 'llamafile-0.9.3')):
                try:
                    info = zf.getinfo(name)
                    size_without_llamafile -= info.compress_size
                except Exception:
                    pass

        size_without_llamafile_mb = size_without_llamafile / (1024 * 1024)

        if size_without_llamafile_mb > max_size_mb:
            print_warn(
                f"Bundle size ({size_without_llamafile_mb:.1f}MB excluding llamafile) exceeds "
                f"target of {max_size_mb}MB. Consider removing unused dependencies."
            )
        else:
            print_ok(f"Bundle size OK: {size_without_llamafile_mb:.1f}MB (excluding llamafile)")


        print("\n  Bundle structure:")
        dirs = set()
        for name in names:
            parts = name.split('/')
            if len(parts) > 1:
                dirs.add(parts[1] if parts[0] == PLUGIN_NAME else parts[0])

        for d in sorted(dirs):
            count = len([n for n in names if f"/{d}/" in n or n.endswith(f"/{d}")])
            print(f"    {PLUGIN_NAME}/{d}/ ({count} files)")

    return True


def print_instructions():
    print("\n" + "=" * 50)
    print("BUILD SUCCESSFUL")
    print("=" * 50)
    print(f"\nBundle: {ZIP_NAME}")
    print(f"Size: {Path(ZIP_NAME).stat().st_size:,} bytes")

    print("\nInstallation Instructions:")
    print("1. Transfer DeckyNews.zip to your Steam Deck")
    print("2. Open Decky Loader settings")
    print("3. Go to 'Developer' > 'Install Plugin from ZIP'")
    print("4. Select DeckyNews.zip")
    print("5. Restart Steam if needed")

    print("\nDebugging:")
    print("  journalctl -u plugin_loader -f | grep -i deckynews")


def main():
    parser = argparse.ArgumentParser(description="Build DeckyNews plugin bundle")
    parser.add_argument("--clean", action="store_true", help="Clean build directories only")
    parser.add_argument("--skip-deps", action="store_true", help="Skip Python dependency bundling")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM dependencies (smaller bundle)")
    args = parser.parse_args()

    print("=" * 50)
    print("Building DeckyNews Plugin for Steam Deck")
    print("=" * 50)

    if args.clean:
        clean_build()
        print("\nClean complete.")
        return 0


    print_step(1, 7, "Cleaning previous builds...")
    clean_build()
    print_ok("Clean complete")


    if not build_frontend():
        return 1


    if not copy_plugin_files():
        return 1


    if not args.skip_deps:
        if not install_python_deps(skip_llm=args.skip_llm):
            print_warn("Dependency installation had errors, but continuing with existing py_modules/")
    else:
        print_step(4, 7, "Skipping Python dependencies (--skip-deps)")
        PY_MODULES_DIR.mkdir(parents=True, exist_ok=True)


    print_step(5, 7, "Ensuring compatibility...")
    print_ok("Using Python zipfile (ensures Unix-compatible paths)")


    if not create_zip_bundle():
        return 1


    if not validate_bundle():
        return 1


    print("\nCleaning up temporary files...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    print_instructions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
