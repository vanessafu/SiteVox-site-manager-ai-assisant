"""DOCX → PDF über LibreOffice headless (soffice --headless --convert-to pdf)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def soffice() -> Optional[str]:
    for name in ("soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        p = shutil.which(name) or (name if Path(name).exists() else None)
        if p:
            return p
    return None


def to_pdf(docx: Path) -> Optional[Path]:
    exe = soffice()
    if not exe:
        return None
    subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                   check=True, capture_output=True, timeout=120)
    pdf = docx.with_suffix(".pdf")
    return pdf if pdf.exists() else None
