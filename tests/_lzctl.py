"""Loads the extension-less lzctl script as a module for tests."""

import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LZCTL = ROOT / ".agents/skills/landing-zone/scripts/lzctl"


def load():
    loader = importlib.machinery.SourceFileLoader("lzctl", str(LZCTL))
    spec = importlib.util.spec_from_loader("lzctl", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
