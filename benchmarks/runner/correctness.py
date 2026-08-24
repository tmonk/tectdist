"""Layered PDF and diagnostics oracle used by the qualification runner."""
import os
import re
import shutil
import subprocess


def _command(name):
    return shutil.which(name)


def _pdf_text(pdf):
    tool = _command("pdftotext")
    if not tool:
        return "", "pdftotext unavailable"
    result = subprocess.run([tool, pdf, "-"], text=True, capture_output=True)
    return result.stdout, "" if result.returncode == 0 else result.stderr.strip()


def _page_count(pdf):
    tool = _command("pdfinfo")
    if not tool:
        return None
    result = subprocess.run([tool, pdf], text=True, capture_output=True)
    if result.returncode:
        return None
    match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else None


def validate(pdf, expected_pages=None, expected_text=(), log_text="", forbid_log_patterns=(),
             requires_bibliography=False, requires_index=False, requires_glossary=False,
             requires_shell_escape=False):
    """Return JSON-safe oracle details; no optional tool means a clear failure."""
    errors = []
    if not os.path.isfile(pdf) or os.path.getsize(pdf) == 0:
        errors.append("PDF does not exist or is empty")
        return {"ok": False, "errors": errors}
    qpdf = _command("qpdf")
    if qpdf:
        checked = subprocess.run([qpdf, "--check", pdf], capture_output=True, text=True)
        if checked.returncode:
            errors.append("qpdf structural check failed: " + checked.stderr.strip())
    text, text_error = _pdf_text(pdf)
    if text_error:
        errors.append(text_error)
    for marker in expected_text:
        if marker not in text:
            errors.append("missing required text: " + marker)
    if expected_pages is not None:
        pages = _page_count(pdf)
        if pages is None:
            errors.append("could not determine PDF page count")
        elif pages != expected_pages:
            errors.append("expected %d pages, found %d" % (expected_pages, pages))
    for pattern in forbid_log_patterns:
        if re.search(pattern, log_text, re.IGNORECASE):
            errors.append("forbidden diagnostic: " + pattern)
    stem, _ = os.path.splitext(pdf)
    if requires_bibliography:
        bbl = stem + ".bbl"
        if not os.path.isfile(bbl) or os.path.getsize(bbl) == 0:
            errors.append("required bibliography output is missing: " + os.path.basename(bbl))
    if requires_index:
        ind = stem + ".ind"
        if not os.path.isfile(ind) or os.path.getsize(ind) == 0:
            errors.append("required index output is missing: " + os.path.basename(ind))
    if requires_glossary:
        gls = stem + ".gls"
        if not os.path.isfile(gls) or os.path.getsize(gls) == 0:
            errors.append("required glossary output is missing: " + os.path.basename(gls))
    if requires_shell_escape and "running shell command" not in log_text.lower():
        errors.append("required shell-escape stage was not observed")
    return {"ok": not errors, "errors": errors, "text_bytes": len(text.encode("utf-8")),
            "stages": {"bibliography": bool(requires_bibliography),
                       "index": bool(requires_index),
                       "glossary": bool(requires_glossary),
                       "shell_escape": bool(requires_shell_escape)}}
