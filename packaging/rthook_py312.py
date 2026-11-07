# -*- coding: utf-8 -*-
"""PyInstaller runtime hook: shim pkgutil.ImpImporter removed in Python 3.12+."""
import pkgutil
import zipimport

if not hasattr(pkgutil, "ImpImporter"):
    pkgutil.ImpImporter = zipimport.zipimporter  # type: ignore[attr-defined]
