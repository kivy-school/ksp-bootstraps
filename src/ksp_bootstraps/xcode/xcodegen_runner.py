"""Download & cache the XcodeGen CLI binary.

Cached under ``~/.kivyschool/xcodegen/<version>/`` to mirror the existing
``cpython_android.py`` pattern.
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Protocol



class XcodeGenProtocol(Protocol):

    def _ensure_installed(self) -> None:
        ...

    def generate(self, spec_path: Path, project_dir: Path) -> None:
        ...
