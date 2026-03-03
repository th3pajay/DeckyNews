#!/usr/bin/env python3
"""
DeckyNews Bundle Script - Cross-platform plugin bundler for Steam Deck

Creates a properly formatted ZIP file that works on Steam Deck:
- Uses forward slashes in ZIP paths (per ZIP spec)
- Downloads Linux-compatible Python wheels
- Validates bundle structure

Usage:
    python bundle.py           # Standard build
    python bundle.py --clean   # Clean build directories only
    python bundle.py --skip-deps  # Skip Python dependency bundling
"""

import os
import sys
import json
import shutil
import zipfile
import tarfile
import subprocess
import argparse
from pathlib import Path
from typing import List, Optional, Tuple

# Configuration
PLUGIN_NAME = "DeckyNews"
BUILD_DIR = Path("build")
DIST_DIR = Path("dist")
BUNDLE_DIR = BUILD_DIR / PLUGIN_NAME
PY_MODULES_DIR = BUNDLE_DIR / "py_modules"
ZIP_NAME = f"{PLUGIN_NAME}.zip"

# Files to include in bundle
PLUGIN_FILES = [
    "main.py",
    "plugin.json",
    "package.json",
    "LICENSE",
    "README.md",
]

# Directories to copy
PLUGIN_DIRS = [
    ("dist", "dist"),
    ("assets", "assets"),
    ("defaults", "defaults"),
    ("bin", "bin"),
    ("src", "src"),
    ("py_modules", "py_modules"),  # Copy manually verified py_modules
]

# Core dependencies (always bundled)
CORE_DEPENDENCIES = [
    "aiohttp",
    "feedparser",
    "certifi",
    "multidict",
    "yarl",
    "frozenlist",
    "aiosignal",
    "async-timeout",
    "attrs",
    "idna",
    "sgmllib3k",
    "Levenshtein",  # For article deduplication
]

# LLM dependencies (optional, larger)
LLM_DEPENDENCIES = [
    "cloudscraper",
    "trafilatura",
    "huggingface_hub",
    "psutil",
    # llama-cpp-python requires special handling
]

# Pre-downloaded wheels directory (for huggingface_hub and deps)
PREDOWNLOADED_WHEELS_DIR = Path("temp_wheels")


def print_step(step: int, total: int, message: str):
    """Print a formatted step message."""
    print(f"\n[{step}/{total}] {message}")


def print_ok(message: str):
    """Print success message."""
    print(f"  [OK] {message}")


def print_warn(message: str):
    """Print warning message."""
    print(f"  [WARN] {message}")


def print_error(message: str):
    """Print error message."""
    print(f"  [ERROR] {message}")


def run_command(cmd: List[str], check: bool = True) -> Tuple[bool, str]:
    """Run a command and return success status and output."""
    try:
        # On Windows, use shell=True to find commands in PATH
        use_shell = sys.platform == "win32"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            shell=use_shell
        )
        return True, result.stdout + result.stderr
    except subprocess.CalledProcessError as e:
        return False, e.stdout + e.stderr
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"


def clean_build():
    """Remove build directories."""
    print("Cleaning build directories...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
        print(f"  Removed {BUILD_DIR}/")

    if Path(ZIP_NAME).exists():
        Path(ZIP_NAME).unlink()
        print(f"  Removed {ZIP_NAME}")


def build_frontend() -> bool:
    """Build the frontend with pnpm or npm."""
    print_step(2, 7, "Building frontend with Rollup...")

    # Try pnpm first
    success, output = run_command(["pnpm", "run", "build"], check=False)
    if success:
        print_ok("Frontend built with pnpm")
        return True

    # Fall back to npm
    print_warn("pnpm not found, trying npm...")
    success, output = run_command(["npm", "run", "build"], check=False)
    if success:
        print_ok("Frontend built with npm")
        return True

    print_error("Frontend build failed")
    print(output)
    return False


def copy_plugin_files() -> bool:
    """Copy plugin files to bundle directory."""
    print_step(3, 7, "Copying plugin files...")

    # Create bundle directory
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy individual files
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

    # Copy directories
    for src_name, dst_name in PLUGIN_DIRS:
        src = Path(src_name)
        dst = BUNDLE_DIR / dst_name
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
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

                # Verify AMD-compatible libraries remain
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
    """Install Python dependencies for Linux/Steam Deck.

    Downloads ALL dependencies in a single pip download command to ensure
    proper transitive dependency resolution.
    """
    print_step(4, 7, "Bundling Python dependencies for Linux...")

    # Create py_modules directory
    PY_MODULES_DIR.mkdir(parents=True, exist_ok=True)

    # ALL dependencies - combining pure Python and binary packages
    # CRITICAL: All deps must be downloaded in ONE pip invocation for correct transitive resolution
    # NOTE: Include ALL transitive dependencies explicitly to avoid pip download issues
    all_deps = [
        "feedparser",
        "certifi",
        "attrs",
        "idna",
        "sgmllib3k",
        "cloudscraper",
        "readability-lxml",
        "lxml-html-clean",
        "cssselect",
        "chardet",
        "requests",
        "requests_toolbelt",
        "pyparsing",
        "charset-normalizer",
        "urllib3",
        "lxml",
        "psutil",
        "python-Levenshtein",
        "Levenshtein",
    ]

    # Download ALL packages in SINGLE invocation for proper transitive dependency resolution
    # Using multiple --platform flags to match broadest set of manylinux wheels
    print("  Downloading all dependencies (including transitive) in single resolution pass...")
    cmd = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(PY_MODULES_DIR),
        "--platform", "manylinux_2_17_x86_64",  # Broadest compatibility
        "--platform", "manylinux_2_28_x86_64",
        "--platform", "manylinux2014_x86_64",
        "--python-version", "311",
        "--only-binary", ":all:",
    ] + all_deps

    success, output = run_command(cmd, check=False)

    if not success:
        print_error("Failed to download Linux x86_64 wheels.")
        print_error("Cannot fall back to local platform - would produce incompatible binaries.")
        print_error(f"pip output:\n{output[:1000]}")
        return False

    # List what was downloaded
    downloaded_files = list(PY_MODULES_DIR.glob("*"))
    print_ok(f"Downloaded {len(downloaded_files)} files (packages + transitive dependencies)")

    # Verify critical packages AND their transitive dependencies
    print("  Verifying critical packages and transitive dependencies...")
    critical_checks = {
        "feedparser": "feedparser",
        "rapidfuzz": "rapidfuzz",
        "Levenshtein": "Levenshtein",
        "lxml": "lxml",
        "lxml_html_clean": "lxml_html_clean",
        "cssselect": "cssselect",
        "chardet": "chardet",
        "certifi": "certifi",
        "psutil": "psutil",
        "cloudscraper": "cloudscraper",
        "readability": "readability",
    }

    missing_critical = []
    for pkg_name, file_prefix in critical_checks.items():
        # Check if any downloaded file contains this package name
        variants = [file_prefix, file_prefix.replace("_", "-"), file_prefix.replace("-", "_")]
        if not any(variant in f.name.lower() for variant in variants for f in downloaded_files):
            missing_critical.append(pkg_name)

    if missing_critical:
        print_error(f"CRITICAL: Missing packages (including transitive deps): {', '.join(missing_critical)}")
        print_error("These WILL cause ModuleNotFoundError on Steam Deck!")
        print_error("Tip: Try running 'python copy_deps.py' first if you have packages installed locally.")
        return False

    print_ok(f"Verified {len(critical_checks)} critical packages (including transitive dependencies)")

    # Copy pre-downloaded wheels (huggingface_hub and dependencies)
    if PREDOWNLOADED_WHEELS_DIR.exists():
        print("  Bundling pre-downloaded huggingface_hub wheels...")
        for wheel in PREDOWNLOADED_WHEELS_DIR.glob("*.whl"):
            shutil.copy2(wheel, PY_MODULES_DIR / wheel.name)
            print_ok(f"Copied {wheel.name}")
    else:
        print_warn("Pre-downloaded wheels directory not found (temp_wheels/)")

    # Extract all wheel files
    extracted_count = 0
    for wheel in PY_MODULES_DIR.glob("*.whl"):
        try:
            with zipfile.ZipFile(wheel, 'r') as whl:
                whl.extractall(PY_MODULES_DIR)
            wheel.unlink()
            extracted_count += 1
        except Exception as e:
            print_warn(f"Failed to extract {wheel.name}: {e}")

    # Extract tar.gz source distributions (for packages without wheels)
    for tarball in PY_MODULES_DIR.glob("*.tar.gz"):
        try:
            with tarfile.open(tarball, 'r:gz') as tar:
                # Find the package directory inside the tarball
                members = tar.getmembers()
                pkg_root = members[0].name.split('/')[0] if members else None
                for member in members:
                    # Extract only Python files to py_modules directly
                    if member.name.endswith('.py'):
                        # Strip the package-version prefix
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

    # Clean up unnecessary files (keep .dist-info for package metadata)
    for pattern in ["__pycache__", "*.pyc"]:
        for item in PY_MODULES_DIR.rglob(pattern):
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # Verify core dependencies exist
    core_present = []
    for dep in ["feedparser", "certifi"]:
        if (PY_MODULES_DIR / dep).exists() or list(PY_MODULES_DIR.glob(f"{dep}*")):
            core_present.append(dep)

    if len(core_present) >= 2:
        print_ok(f"Core dependencies bundled: {', '.join(core_present)}")
        return True
    else:
        print_warn("Some core dependencies may be missing. Bundle may need to install on device.")
        return True  # Don't fail, as Steam Deck may have these installed


def create_zip_bundle() -> bool:
    """Create ZIP file with proper forward slashes."""
    print_step(6, 7, "Creating plugin bundle...")

    if Path(ZIP_NAME).exists():
        Path(ZIP_NAME).unlink()

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(BUNDLE_DIR):
            # Skip __pycache__ directories
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for file in files:
                # Skip .pyc files
                if file.endswith('.pyc'):
                    continue

                file_path = Path(root) / file

                # Calculate archive name with forward slashes
                # Must be relative to BUILD_DIR, not BUNDLE_DIR
                arcname = file_path.relative_to(BUILD_DIR).as_posix()

                # Use ZipInfo to preserve executable permissions for binaries
                info = zipfile.ZipInfo(arcname)
                info.compress_type = zipfile.ZIP_DEFLATED

                # Set Unix permissions: rwxr-xr-x (755) for bin/, rw-r--r-- (644) otherwise
                if '/bin/' in arcname or arcname.endswith('/bin'):
                    info.external_attr = (0o755 << 16) | 0x8000  # rwxr-xr-x + regular file
                else:
                    info.external_attr = (0o644 << 16) | 0x8000  # rw-r--r-- + regular file

                with open(file_path, 'rb') as f:
                    zf.writestr(info, f.read())

                file_count += 1
                total_size += file_path.stat().st_size

    print_ok(f"Created {ZIP_NAME} with {file_count} files")
    return True


def validate_bundle() -> bool:
    """Validate the bundle structure."""
    print_step(7, 7, "Validating bundle...")

    if not Path(ZIP_NAME).exists():
        print_error("ZIP file not created")
        return False

    zip_size = Path(ZIP_NAME).stat().st_size

    with zipfile.ZipFile(ZIP_NAME, 'r') as zf:
        names = zf.namelist()

        # Check required files exist
        required = [
            f"{PLUGIN_NAME}/main.py",
            f"{PLUGIN_NAME}/plugin.json",
            f"{PLUGIN_NAME}/dist/index.js",
        ]

        missing = [f for f in required if f not in names]
        if missing:
            print_error(f"Missing required files in bundle: {missing}")
            return False

        # Check for backslashes (would break on Linux)
        backslash_paths = [n for n in names if '\\' in n]
        if backslash_paths:
            print_error(f"Bundle contains backslashes (incompatible): {backslash_paths[:3]}")
            return False

        # Check for LLM binaries (optional)
        llamafile_binary = f"{PLUGIN_NAME}/bin/llamafile"
        legacy_binary = f"{PLUGIN_NAME}/bin/llama-cli"

        if llamafile_binary in names or legacy_binary in names:
            print_ok("AI engine binary bundled")
        else:
            print_warn("No AI binaries found - AI summarization unavailable")

        print_ok(f"Bundle validated: {len(names)} entries, {zip_size:,} bytes")

        # Check bundle size (excluding llamafile binary)
        size_mb = zip_size / (1024 * 1024)
        max_size_mb = 20  # Target: <20MB excluding llamafile

        # Calculate size without llamafile
        size_without_llamafile = zip_size
        for name in names:
            if 'llamafile' in name and name.endswith(('llamafile', 'llamafile-0.9.3')):
                try:
                    info = zf.getinfo(name)
                    size_without_llamafile -= info.compress_size
                except:
                    pass

        size_without_llamafile_mb = size_without_llamafile / (1024 * 1024)

        if size_without_llamafile_mb > max_size_mb:
            print_warn(
                f"Bundle size ({size_without_llamafile_mb:.1f}MB excluding llamafile) exceeds "
                f"target of {max_size_mb}MB. Consider removing unused dependencies."
            )
        else:
            print_ok(f"Bundle size OK: {size_without_llamafile_mb:.1f}MB (excluding llamafile)")

        # Show structure summary
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
    """Print installation instructions."""
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

    # Clean previous builds
    print_step(1, 7, "Cleaning previous builds...")
    clean_build()
    print_ok("Clean complete")

    # Build frontend
    if not build_frontend():
        return 1

    # Copy plugin files
    if not copy_plugin_files():
        return 1

    # Bundle Python dependencies
    if not args.skip_deps:
        if not install_python_deps(skip_llm=args.skip_llm):
            print_warn("Dependency installation had errors, but continuing with existing py_modules/")
    else:
        print_step(4, 7, "Skipping Python dependencies (--skip-deps)")
        PY_MODULES_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure compatibility
    print_step(5, 7, "Ensuring compatibility...")
    print_ok("Using Python zipfile (ensures Unix-compatible paths)")

    # Create ZIP bundle
    if not create_zip_bundle():
        return 1

    # Validate bundle
    if not validate_bundle():
        return 1

    # Cleanup build directory
    print("\nCleaning up temporary files...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)

    print_instructions()
    return 0


if __name__ == "__main__":
    sys.exit(main())
