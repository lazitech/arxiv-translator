#!/usr/bin/env python3
"""
Use local TeX Live to compile a LaTeX project with XeLaTeX.
Usage: python compile.py <work_dir> <main_tex> <output_pdf_path>

main_tex: path relative to work_dir (e.g. ms.tex), or absolute path to the main file.
output_pdf_path: full path for the output PDF; if an existing directory is passed, write <main_basename>.pdf there.
"""
import os
import re
import shutil
import subprocess
import sys


_BIBLATEX_RE = re.compile(r"\\(?:usepackage(?:\[[^\]]*\])?\{biblatex\}|addbibresource\{)")
_BIBTEX_CMD_RE = re.compile(r"\\bibliography\{")
_THEBIB_RE = re.compile(r"\\begin\{thebibliography\}")
_BBL_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{[^}]+\.bbl\}")
_CMD_ALREADY_DEFINED_RE = re.compile(r"LaTeX Error: Command \\([A-Za-z@]+) already defined")
_CMD_ALREADY_DEFINED_WITH_PATH_RE = re.compile(
    r"^\./(?P<path>[^:\n]+):(?P<lineno>\d+):\s+LaTeX Error: Command \\(?P<cmd>[A-Za-z@]+) already defined",
    re.MULTILINE,
)
_BEGIN_DOCUMENT_RE = re.compile(r"\\begin\{document\}")
_CJK_RE = re.compile(r"[㐀-鿿]")
_UNRESOLVED_CITE_MARKERS = ("[?", "?]")
_UNRESOLVED_REF_MARKERS = ("??",)
_SOURCE_TEXT_EXTS = {
    ".tex",
    ".sty",
    ".cls",
    ".bst",
    ".bib",
    ".bbx",
    ".cbx",
    ".cfg",
}
_AUTO_CJK_PREAMBLE = "\n".join(
    (
        r"\usepackage{xeCJK}",
        r"\setCJKmainfont{Noto Serif CJK SC}",
        r"\setlength{\emergencystretch}{3em}",
        "",
    )
)


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _norm_relpath(path, root):
    rel = os.path.relpath(path, root)
    rel = os.path.normpath(rel)
    if os.name == "nt":
        rel = rel.replace("\\", "/")
    return rel


def _iter_project_files(work_dir):
    for root, _, files in os.walk(work_dir):
        for fname in files:
            abs_path = os.path.join(root, fname)
            yield abs_path, _norm_relpath(abs_path, work_dir)


def _collect_source_texts(work_dir):
    texts = {}
    for abs_path, rel in _iter_project_files(work_dir):
        if os.path.splitext(rel)[1].lower() not in _SOURCE_TEXT_EXTS:
            continue
        try:
            texts[rel] = _read_text(abs_path)
        except OSError:
            continue
    return texts


def _main_tex_relative(work_dir, main_tex):
    work_dir = os.path.abspath(work_dir)
    if os.path.isabs(main_tex):
        main_abs = os.path.abspath(main_tex)
    else:
        main_abs = os.path.abspath(os.path.join(work_dir, main_tex))
    try:
        rel = os.path.relpath(main_abs, work_dir)
    except ValueError:
        rel = main_tex
    if rel.startswith("..") or os.path.isabs(rel):
        print(
            "Error: main file must be inside work_dir.\n"
            f"  work_dir={work_dir}\n"
            f"  main_tex={main_tex} -> {main_abs}",
            file=sys.stderr,
        )
        sys.exit(1)
    rel = os.path.normpath(rel)
    if os.name == "nt":
        rel = rel.replace("\\", "/")
    return work_dir, rel


def _resolve_output_pdf(output_path, main_tex_rel):
    output_path = os.path.expanduser(output_path)
    if output_path.endswith(os.sep) or (os.path.exists(output_path) and os.path.isdir(output_path)):
        base = os.path.splitext(os.path.basename(main_tex_rel))[0] + ".pdf"
        return os.path.join(output_path.rstrip(os.sep), base)
    parent = os.path.dirname(os.path.abspath(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return output_path


def _find_prebuilt_bbl(work_dir, main_rel):
    main_stem = os.path.splitext(os.path.basename(main_rel))[0].lower()
    bbl_files = []
    for _, rel in _iter_project_files(work_dir):
        if rel.lower().endswith(".bbl"):
            bbl_files.append(rel)
    if not bbl_files:
        return None
    for rel in bbl_files:
        if os.path.splitext(os.path.basename(rel))[0].lower() == main_stem:
            return rel
    if len(bbl_files) == 1:
        return bbl_files[0]
    return None


def _detect_bibliography_setup(work_dir, main_rel):
    tex_blob = "\n".join(
        text for rel, text in _collect_source_texts(work_dir).items() if rel.lower().endswith(".tex")
    )
    has_bib_files = any(rel.lower().endswith(".bib") for _, rel in _iter_project_files(work_dir))
    prebuilt_bbl = _find_prebuilt_bbl(work_dir, main_rel)

    if _BIBLATEX_RE.search(tex_blob):
        return "biber", None

    if _THEBIB_RE.search(tex_blob) or _BBL_INPUT_RE.search(tex_blob):
        return None, None

    if _BIBTEX_CMD_RE.search(tex_blob):
        if prebuilt_bbl and not has_bib_files:
            return None, prebuilt_bbl
        return "bibtex", None

    if has_bib_files:
        return "bibtex", None

    return None, None


def _detect_compiler(work_dir, main_rel):
    main_text = _read_text(os.path.join(work_dir, main_rel))

    if "\\usepackage{xeCJK}" in main_text or "\\setCJKmainfont" in main_text:
        return "xelatex"
    if "\\usepackage{luatexja}" in main_text or "\\usepackage{luatexja-fontspec}" in main_text or "\\setmainjfont" in main_text:
        return "lualatex"

    return "xelatex"


def _patch_file_replace(path, pattern, repl, count=1):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return False
    new_text, n = re.subn(pattern, repl, text, count=count, flags=re.MULTILINE)
    if n <= 0:
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    except OSError:
        return False
    return True


def _project_contains_cjk(work_dir):
    for rel, text in _collect_source_texts(work_dir).items():
        if rel.lower().endswith(".tex") and _CJK_RE.search(text):
            return True
    return False


def _ensure_cjk_support(work_dir, main_rel):
    path = os.path.join(work_dir, main_rel)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return False

    if not _project_contains_cjk(work_dir):
        return False

    if any(
        tok in text
        for tok in (
            "\\usepackage{luatexja}",
            "\\usepackage{luatexja-fontspec}",
            "\\usepackage{xeCJK}",
            "\\usepackage{ctex}",
            "\\setmainjfont{",
            "\\setCJKmainfont{",
        )
    ):
        return False

    if not _BEGIN_DOCUMENT_RE.search(text):
        return False

    preamble = _AUTO_CJK_PREAMBLE
    if "\\usepackage{fontspec}" in text:
        preamble = preamble.replace("\\usepackage{fontspec}\n", "", 1)

    new_text, n = _BEGIN_DOCUMENT_RE.subn(lambda _: preamble + r"\begin{document}", text, count=1)
    if n <= 0:
        return False

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    except OSError:
        return False

    return True


def _preflight_comment_inputenc_fontenc(work_dir, main_rel):
    """Comment out inputenc/fontenc and pdfoutput that conflict with XeLaTeX/LuaLaTeX."""
    path = os.path.join(work_dir, main_rel)
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return False

    uses_unicode_stack = any(
        tok in text
        for tok in (
            "\\usepackage{fontspec}",
            "\\usepackage{xeCJK}",
            "\\usepackage{luatexja}",
            "\\usepackage{ctex}",
        )
    )
    if not uses_unicode_stack:
        return False

    changed = False

    def _comment_line(m):
        indent = m.group("indent") or ""
        line = m.group(0)
        return indent + "% " + line[len(indent):]

    for pat in (
        r"^(?P<indent>\s*)\\usepackage\[[^\]]*\]\{inputenc\}.*$",
        r"^(?P<indent>\s*)\\usepackage\[[^\]]*\]\{fontenc\}.*$",
        r"^(?P<indent>\s*)\\pdfoutput\s*=.*$",
    ):
        if re.search(pat, text, flags=re.MULTILINE):
            text = re.sub(pat, _comment_line, text, count=1, flags=re.MULTILINE)
            changed = True

    if changed:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            return False
    return changed


def _fix_command_already_defined(work_dir, rel_path, cmd):
    abs_path = os.path.join(work_dir, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return False

    cmd_esc = re.escape(cmd)
    pat1 = re.compile(rf"^\s*\\newcommand\*?\s*\\{cmd_esc}\b")
    pat2 = re.compile(rf"^\s*\\newcommand\*?\s*\{{\\{cmd_esc}\}}\b")

    changed = False
    for i, line in enumerate(lines):
        if pat1.search(line) or pat2.search(line):
            lines[i] = re.sub(r"\\newcommand\*?", r"\\renewcommand", line, count=1)
            changed = True
            break

    if not changed:
        return False

    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        return False

    return True


def _extract_pdf_text(pdf_path):
    try:
        import pypdf  # type: ignore
    except Exception:
        return None

    try:
        reader = pypdf.PdfReader(pdf_path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return None


def _has_unresolved_markers(pdf_path):
    text = _extract_pdf_text(pdf_path)
    if not text:
        return False
    return any(m in text for m in _UNRESOLVED_CITE_MARKERS) or any(m in text for m in _UNRESOLVED_REF_MARKERS)


def _read_compiler_log(work_dir, main_rel):
    """Read the .log file for the main document."""
    log_name = os.path.splitext(os.path.basename(main_rel))[0] + ".log"
    log_path = os.path.join(work_dir, log_name)
    try:
        return _read_text(log_path)
    except OSError:
        return ""


def _try_fix_from_logs(work_dir, main_rel, logs_text):
    applied = False

    m = _CMD_ALREADY_DEFINED_WITH_PATH_RE.search(logs_text)
    if m:
        local_path = m.group("path")
        cmd = m.group("cmd")
        if _fix_command_already_defined(work_dir, local_path, cmd):
            applied = True

    if not applied:
        m2 = _CMD_ALREADY_DEFINED_RE.search(logs_text)
        if m2:
            cmd = m2.group(1)
            if _fix_command_already_defined(work_dir, main_rel, cmd):
                applied = True

    return applied


def compile_local(work_dir, main_tex, output_path):
    work_dir, main_rel = _main_tex_relative(work_dir, main_tex)
    output_path = _resolve_output_pdf(output_path, main_rel)
    bibliography_command, _prebuilt_bbl = _detect_bibliography_setup(work_dir, main_rel)
    compiler = _detect_compiler(work_dir, main_rel)
    main_stem = os.path.splitext(main_rel)[0]
    pdf_in_work = os.path.join(work_dir, main_stem + ".pdf")

    max_attempts = 3
    last_error = None

    for attempt in range(1, max_attempts + 1):
        _ensure_cjk_support(work_dir, main_rel)
        _preflight_comment_inputenc_fontenc(work_dir, main_rel)

        # --- First pass ---
        result = subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", main_rel],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logs_text = result.stderr + "\n" + _read_compiler_log(work_dir, main_rel)
            if attempt < max_attempts and _try_fix_from_logs(work_dir, main_rel, logs_text):
                continue
            last_error = logs_text
            print("Compilation failed (attempt %d/%d)." % (attempt, max_attempts), file=sys.stderr)
            print("\n--- compiler log (truncated) ---", file=sys.stderr)
            print(logs_text[-8000:], file=sys.stderr)
            sys.exit(1)

        # --- BibTeX ---
        if bibliography_command:
            bib_stem = main_stem
            subprocess.run(
                [bibliography_command, bib_stem],
                cwd=work_dir,
                capture_output=True,
                text=True,
            )

        # --- Second pass ---
        subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", main_rel],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )

        # --- Third pass ---
        subprocess.run(
            [compiler, "-interaction=nonstopmode", "-halt-on-error", main_rel],
            cwd=work_dir,
            capture_output=True,
            text=True,
        )

        if not os.path.exists(pdf_in_work):
            last_error = "PDF was not produced."
            if attempt < max_attempts:
                continue
            print("Compilation failed: " + last_error, file=sys.stderr)
            sys.exit(1)

        if _has_unresolved_markers(pdf_in_work):
            last_error = "PDF contains unresolved markers (e.g. '??' or '[?]')."
            if attempt < max_attempts:
                continue
            print("Compilation failed: " + last_error, file=sys.stderr)
            sys.exit(1)

        # --- Copy PDF to output ---
        shutil.copy2(pdf_in_work, output_path)
        print("Wrote PDF: " + os.path.abspath(output_path))
        return True

    print("Compilation failed.", file=sys.stderr)
    if last_error:
        print(last_error, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python compile.py <work_dir> <main_tex> <output_pdf_path>",
            file=sys.stderr,
        )
        sys.exit(2)
    compile_local(sys.argv[1], sys.argv[2], sys.argv[3])
