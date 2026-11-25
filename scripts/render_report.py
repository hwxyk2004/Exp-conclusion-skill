"""Render one UTF-8 experiment progress report as a searchable A4 PDF."""

import argparse
import json
import os
import re
import tempfile
from functools import partial
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.platypus import (
    CondPageBreak, Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, TableStyle,
)


CITATION_COLOR = "#174875"


def register_fonts(custom_font):
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    choices = [windows_fonts / "simsun.ttc", windows_fonts / "msyh.ttc",
               windows_fonts / "Deng.ttf", Path("/System/Library/Fonts/STHeiti Light.ttc"),
               Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]
    body = custom_font or next((path for path in choices if path.is_file()), None)
    if body is None or not body.is_file():
        raise ValueError("找不到中文字体。请使用 --font 传入可嵌入的中文 TrueType 字体路径。")
    for name, path in [("Song", body), ("Kai", windows_fonts / "simkai.ttf"),
                       ("Hei", windows_fonts / "simhei.ttf"), ("Roman", windows_fonts / "times.ttf")]:
        fallback = body if custom_font and name in ("Hei", "Kai") else path
        pdfmetrics.registerFont(TTFont(name, str(fallback if fallback.is_file() else body)))


def strings(value, field):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} 应为字符串数组")
    return value


def field_text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少非空文本字段 {key}")
    return value


def text_markup(text, font):
    # Use the template's Western face in Song-style prose. Keep CJK punctuation
    # full-width, even when Times provides a substitute glyph.
    primary = pdfmetrics.getFont(font).face.charToGlyph
    roman = pdfmetrics.getFont("Roman").face.charToGlyph

    def face(char):
        code = ord(char)
        if font == "Song" and code < 0x0250 and roman.get(code):
            return "Roman"
        if primary.get(code) or not char.isprintable() or char.isspace():
            return font
        if roman.get(code):
            return "Roman"
        raise ValueError(f"当前字体缺少 {char} (U+{code:04X})。请用 --font 指定覆盖该字符的中文字体，或使用等义写法。")

    runs = []
    for name, chars in groupby(text, key=face):
        value = escape("".join(chars)).replace("\n", "<br/>")
        runs.append(value if name == font else f'<font name="{name}">{value}</font>')
    return "".join(runs)


def paragraph(value, style, *, reference_count=0, prefix=""):
    pieces = [prefix]
    pos = 0
    if reference_count:
        for match in re.finditer(r"\[([1-9]\d*)\](?:\d+[-–]\d+)?", value):
            number = int(match[1])
            if number > reference_count:
                continue
            pieces.append(text_markup(value[pos:match.start()], style.fontName))
            label = text_markup(match[0], style.fontName)
            pieces.append(f'<super><link href="#ref-{number}" color="{CITATION_COLOR}"><u>{label}</u></link></super>')
            pos = match.end()
    pieces.append(text_markup(value[pos:], style.fontName))
    return Paragraph("".join(pieces), style)


def make_styles():
    base = ParagraphStyle("Base", fontName="Song", fontSize=10.5, leading=15.7,
                          textColor=colors.black, wordWrap="CJK")
    heading = ParagraphStyle("Heading", parent=base, leading=23, spaceBefore=6,
                             spaceAfter=3, keepWithNext=True)
    return {
        "body": ParagraphStyle("Body", parent=base, firstLineIndent=24.1, alignment=TA_JUSTIFY),
        "title": ParagraphStyle("Title", parent=base, fontSize=22, leading=23, alignment=TA_CENTER,
                                spaceAfter=9, keepWithNext=True),
        "meta": ParagraphStyle("Period", parent=base, fontSize=9, leading=14, spaceAfter=3),
        "summary": ParagraphStyle("Summary", parent=base, leading=15, spaceAfter=4),
        1: ParagraphStyle("Chapter", parent=heading, fontName="Kai", fontSize=16, alignment=TA_CENTER),
        2: ParagraphStyle("Subheading", parent=heading, fontName="Hei"),
        3: ParagraphStyle("MinorHeading", parent=heading, firstLineIndent=21),
        "references": ParagraphStyle("Bibliography", parent=heading, fontName="Hei", fontSize=13),
        "reference": ParagraphStyle("Reference", parent=base, leftIndent=22, firstLineIndent=-22,
                                    leading=14, spaceAfter=2, allowWidows=0, allowOrphans=0),
        "cell": ParagraphStyle("Cell", parent=base, fontSize=10, leading=14),
        "header": ParagraphStyle("Header", parent=base, fontName="Hei", fontSize=10, leading=14),
        "caption": ParagraphStyle("Caption", parent=base, fontSize=9, leading=14, spaceBefore=4,
                                  alignment=TA_CENTER),
    }


def report_table(spec, styles, width, para):
    headers = strings(spec.get("headers"), "table.headers")
    rows = spec.get("rows")
    if not headers or not isinstance(rows, list):
        raise ValueError("表格需要表头和数据行数组")
    data = [[para(label, styles["header"]) for label in headers]]
    for index, row in enumerate(rows, 1):
        strings(row, f"table.rows[{index - 1}]")
        if len(row) != len(headers):
            raise ValueError(f"表格第 {index} 行的列数与表头不符")
        data.append([para(value, styles["cell"]) for value in row])
    table = LongTable(data, colWidths=[width / len(headers)] * len(headers),
                      repeatRows=1, splitInRow=1, spaceBefore=4, spaceAfter=7)
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def report_figure(spec, base, styles, width, para):
    path = base / field_text(spec, "path")
    caption = field_text(spec, "caption")
    image_width, image_height = ImageReader(str(path)).getSize()
    scale = min(width / image_width, 138 * mm / image_height, 1.0)
    image = Image(str(path), width=image_width * scale, height=image_height * scale)
    return KeepTogether([image, para(caption, styles["caption"])])


def section_number(number):
    digits = "〇一二三四五六七八九"
    if number < 10:
        return digits[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        return (digits[tens] if tens > 1 else "") + "十" + (digits[ones] if ones else "")
    return str(number)


def reference_entry(entry, index, style):
    if isinstance(entry, str) and entry.strip():
        content = text_markup(entry, style.fontName)
    elif isinstance(entry, dict):
        citation = field_text(entry, "text")
        title = field_text(entry, "title")
        url = field_text(entry, "url")
        parts = urlsplit(url)
        if title not in citation or parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"文献 {index} 的题名应出现在题录中，并提供完整的 HTTP(S) 来源地址")
        before, _, after = citation.partition(title)
        link = f'<link href={quoteattr(url)} color="{CITATION_COLOR}"><u>{text_markup(title, style.fontName)}</u></link>'
        content = text_markup(before, style.fontName) + link + text_markup(after, style.fontName)
    else:
        raise ValueError(f"文献 {index} 应为非空的题录字符串或含 text、title、url 的对象")
    return Paragraph(f'<a name="ref-{index}"/><font name="Roman">[{index}] </font>{content}', style)


def render(source, destination, custom_font):
    if destination.suffix.lower() != ".pdf" or source.resolve() == destination.resolve():
        raise ValueError("请指定独立的 .pdf 输出文件")
    report = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError("报告根节点应为 JSON 对象")
    title = field_text(report, "title")
    register_fonts(custom_font)
    styles = make_styles()
    sections = report.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections 应为至少包含一个章节的数组")

    references = report.get("references", [])
    if not isinstance(references, list):
        raise ValueError("references 应为按正文首次引用顺序排列的数组")
    para = partial(paragraph, reference_count=len(references))
    margin = 63.8
    width = A4[0] - 2 * margin
    story = [paragraph(title, styles["title"]),
             para(field_text(report, "summary"), styles["summary"],
                  prefix='<font name="Hei">摘　要：</font>'),
             paragraph(field_text(report, "period"), styles["meta"])]
    counts = [0, 0, 0]
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("每个章节应为 JSON 对象")
        values = strings(section.get("paragraphs", []), "paragraphs")
        level = section.get("level", 1)
        if type(level) is not int or level not in (1, 2, 3):
            raise ValueError("章节 level 应为 1、2 或 3")
        counts[level - 1] += 1
        counts[level:] = [0] * (3 - level)
        number = section_number(counts[level - 1])
        prefixes = {1: f"{number}、", 2: f"（{number}）", 3: f"{counts[level - 1]}. "}
        name = field_text(section, "title")
        heading = paragraph(name if name.startswith(prefixes[level]) else prefixes[level] + name,
                            styles[level])
        if not values and "table" in section:
            # Let the table start on a partly filled page with room for its first rows.
            heading.keepWithNext = False
            heading_height = heading.wrap(width, A4[1])[1]
            story.append(CondPageBreak(heading_height + 90))
        story.append(heading)
        for value in values:
            story.append(para(value, styles["body"]))
        if "table" in section:
            story.append(report_table(section["table"], styles, width, para))
        if "figure" in section:
            story.append(report_figure(section["figure"], source.parent, styles, width, para))
    if references:
        story.append(paragraph("参考文献", styles["references"]))
        for index, entry in enumerate(references, 1):
            story.append(reference_entry(entry, index, styles["reference"]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Roman", 12)
        canvas.drawCentredString(A4[0] / 2, 36, str(document.page))
        canvas.restoreState()

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".pdf", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        # Each SimpleDocTemplate frame adds a six-point inset of its own.
        doc = SimpleDocTemplate(str(temporary), pagesize=A4, title=title, author="",
                                leftMargin=margin - 6, rightMargin=margin - 6,
                                topMargin=65.2 - 6, bottomMargin=65.2 - 6)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="UTF-8 报告 JSON")
    parser.add_argument("destination", type=Path, help="输出 PDF")
    parser.add_argument("--font", type=Path, help="可嵌入的中文 TrueType 字体（.ttf 或 .ttc）")
    args = parser.parse_args()
    try:
        render(args.source, args.destination, args.font)
    except (OSError, ValueError, TTFError) as error:
        parser.exit(1, f"{error}\n")
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
