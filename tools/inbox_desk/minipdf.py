"""A tiny one-page PDF writer (Python stdlib only).

Why it exists: a Gmail draft attachment is passed to the Gmail connector as base64 text, which the model has to
copy into the tool call. A browser-printed PDF embeds fonts and runs 30 KB and up; this one uses the PDF
built-in Helvetica fonts, compresses the page, and stays near 3 KB, so the copy is short and safe.

It draws: filled rectangles, lines, text in Helvetica / Helvetica-Bold (WinAnsi), word-wrapped paragraphs, and
clickable link areas. That is all the one-page plan needs.
"""
import zlib

# Helvetica and Helvetica-Bold advance widths (1/1000 em) for ASCII 32..126, from the standard Adobe AFM files.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
         556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
         500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469,
         556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
         278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
         556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
         556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584,
         556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
         333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_SUBS = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "...",
         "\u00a0": " ", "\u2022": "-"}


def clean(s):
    s = "".join(_SUBS.get(ch, ch) for ch in str(s or ""))
    return "".join(ch if 32 <= ord(ch) < 127 or 160 <= ord(ch) < 256 else "?" for ch in s)


def width(s, size, bold=False):
    tbl = _BOLD if bold else _HELV
    return sum(tbl[ord(c) - 32] if 32 <= ord(c) < 127 else 556 for c in s) * size / 1000.0


def wrap(text, size, max_w, bold=False):
    out = []
    for para in clean(text).split("\n"):
        line = ""
        for word in para.split(" "):
            trial = (line + " " + word).strip() if line else word
            if width(trial, size, bold) <= max_w or not line:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def _esc(s):
    return clean(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return " ".join("%.3f" % (int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


class Page:
    """Letter page, origin at the TOP left (y grows down), converted to PDF space on output."""

    def __init__(self, w=612, h=792):
        self.w, self.h = w, h
        self.ops, self.links = [], []

    def rect(self, x, y, w, h, fill):
        self.ops.append("%s rg %.2f %.2f %.2f %.2f re f" % (_rgb(fill), x, self.h - y - h, w, h))

    def line(self, x1, y1, x2, y2, color, lw=0.75):
        self.ops.append("%s RG %.2f w %.2f %.2f m %.2f %.2f l S" % (_rgb(color), lw, x1, self.h - y1, x2, self.h - y2))

    def text(self, x, y, s, size=11, bold=False, color="#181b18"):
        """y is the baseline, measured from the top."""
        self.ops.append("BT /%s %.1f Tf %s rg %.2f %.2f Td (%s) Tj ET" % ("F2" if bold else "F1", size, _rgb(color),
                                                                       x, self.h - y, _esc(s)))

    def para(self, x, y, s, size=11, max_w=500, bold=False, color="#181b18", lead=1.38):
        """Wrapped paragraph from baseline y. Returns the y below it."""
        for ln in wrap(s, size, max_w, bold):
            self.text(x, y, ln, size, bold, color)
            y += size * lead
        return y

    def link(self, x, y_top, w, h, url):
        self.links.append((x, self.h - y_top - h, x + w, self.h - y_top, clean(url)))


def build(page, title="", author=""):
    """bytes of a one-page PDF."""
    content = zlib.compress("\n".join(page.ops).encode("latin-1"), 9)
    objs = []
    annots = []
    first_annot = 7
    for i, (x1, y1, x2, y2, url) in enumerate(page.links):
        annots.append("%d 0 R" % (first_annot + i))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
                 "/Contents 6 0 R%s >>" % (page.w, page.h, (" /Annots [" + " ".join(annots) + "]") if annots else ""))
                .encode("latin-1"))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream")
    for (x1, y1, x2, y2, url) in page.links:
        objs.append(("<< /Type /Annot /Subtype /Link /Rect [%.2f %.2f %.2f %.2f] /Border [0 0 0] "
                     "/A << /S /URI /URI (%s) >> >>" % (x1, y1, x2, y2, _esc(url))).encode("latin-1"))
    objs.append(("<< /Title (%s) /Author (%s) /Producer (Surven Inbox Desk) >>" % (_esc(title), _esc(author)))
                .encode("latin-1"))
    info_num = len(objs)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, info_num, xref)
    return bytes(out)
