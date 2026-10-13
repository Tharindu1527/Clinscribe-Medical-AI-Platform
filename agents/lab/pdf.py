"""A minimal text-only PDF writer (no dependency) for synthetic lab reports, and the report layout.

Reports are rendered from Synthea observations so every parsed value has a known source value
(evals/lab/lab_eval.py). Real reports vary in layout; this one is fixed, which is what the parser
measures against (see the limits in the evaluation report).
"""

from collections.abc import Sequence


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(lines: Sequence[str], font_size: int = 10) -> bytes:
    """One A4 page per 60 lines, Helvetica, plain text lines."""
    pages = [list(lines[i : i + 60]) for i in range(0, max(len(lines), 1), 60)]
    objects: list[bytes] = [b"", b""]  # 1: catalog, 2: pages (filled below)
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
    kids = []
    for page in pages:
        text = f"BT /F1 {font_size} Tf 14 TL 50 800 Td "
        text += " ".join(f"({_escape(line)}) Tj T*" for line in page) + " ET"
        stream = text.encode("latin-1", "replace")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % content
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def report_lines(
    patient_name: str, birth_date: str, collected: str, rows: Sequence[tuple[str, str, str, str]]
) -> list[str]:
    """rows: (test name, value, unit, reference interval)."""
    lines = [
        "Synthetic Clinical Laboratory (demo data)",
        "LABORATORY REPORT",
        f"Patient: {patient_name}",
        f"Date of birth: {birth_date}",
        f"Collected: {collected}",
        "",
        "Test  |  Result  |  Unit  |  Reference interval",
    ]
    lines += [f"{name}  |  {value}  |  {unit}  |  {ref}" for name, value, unit, ref in rows]
    lines += ["", "End of report"]
    return lines
