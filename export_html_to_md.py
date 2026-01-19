import argparse
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import html2text
from bs4 import BeautifulSoup


def make_converter() -> html2text.HTML2Text:
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = False
    converter.body_width = 0
    converter.single_line_break = False
    converter.protect_links = True
    converter.unicode_snob = True
    converter.ignore_tables = False
    return converter


def get_main_content(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Common Confluence export containers
    main = (
        soup.find(id="main-content")
        or soup.find("div", class_="wiki-content")
        or soup.find("div", class_="content")
        or soup.find(id="content")
        or soup.find("div", class_="pageSection")
    )
    if main is None:
        main = soup.body or soup
    return str(main)


def extract_page_id(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": "ajs-page-id"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    data = soup.find(attrs={"data-page-id": True})
    if data:
        return str(data.get("data-page-id")).strip()
    return None


def build_html_map(input_dir: Path, output_dir: Path) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for html_path in input_dir.rglob("*.html"):
        rel = html_path.relative_to(input_dir).as_posix()
        target = output_dir / html_path.relative_to(input_dir)
        target = target.with_suffix(".md")
        mapping[rel] = target
    for html_path in input_dir.rglob("*.htm"):
        rel = html_path.relative_to(input_dir).as_posix()
        target = output_dir / html_path.relative_to(input_dir)
        target = target.with_suffix(".md")
        mapping[rel] = target
    return mapping


def build_page_id_map(input_dir: Path, html_map: Dict[str, Path]) -> Dict[str, Path]:
    page_id_map: Dict[str, Path] = {}
    for rel, md_path in html_map.items():
        html_path = input_dir / rel
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        page_id = extract_page_id(html)
        if page_id:
            page_id_map[page_id] = md_path
    return page_id_map


def rewrite_links(
    html: str,
    html_map: Dict[str, Path],
    page_id_map: Dict[str, Path],
    current_html: Path,
    current_md: Path,
    input_dir: Path,
) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def normalize_href(href: str) -> Tuple[str, Optional[str]]:
        if "#" in href:
            base, frag = href.split("#", 1)
            return base, "#" + frag
        return href, None

    for tag in soup.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        url = tag.get(attr)
        if not url:
            continue
        if re.match(r"^(https?://|mailto:|#)", url):
            continue

        base, frag = normalize_href(url)
        parsed = urlparse(base)

        # Handle viewpage.action?pageId=123
        if parsed.query:
            qs = parse_qs(parsed.query)
            page_id = qs.get("pageId", [None])[0]
            if page_id and page_id in page_id_map:
                md_path = page_id_map[page_id]
                new_rel = os.path.relpath(md_path, current_md.parent)
                new_rel = new_rel.replace("\\", "/")
                tag[attr] = new_rel + (frag or "")
                continue

        if parsed.scheme or parsed.netloc:
            continue

        base_path = (current_html.parent / unquote(parsed.path)).resolve()
        try:
            rel = base_path.relative_to(input_dir).as_posix()
        except ValueError:
            continue

        if rel in html_map:
            md_path = html_map[rel]
            new_rel = os.path.relpath(md_path, current_md.parent)
            new_rel = new_rel.replace("\\", "/")
            tag[attr] = new_rel + (frag or "")
        else:
            # For non-HTML files keep relative path
            new_rel = os.path.relpath(base_path, current_md.parent)
            new_rel = new_rel.replace("\\", "/")
            tag[attr] = new_rel + (frag or "")

    return str(soup)


def convert_html_file(
    src_path: Path,
    dst_path: Path,
    html_map: Dict[str, Path],
    page_id_map: Dict[str, Path],
    input_dir: Path,
    converter: html2text.HTML2Text,
) -> None:
    html = src_path.read_text(encoding="utf-8", errors="ignore")
    main_html = get_main_content(html)
    main_html = rewrite_links(main_html, html_map, page_id_map, src_path, dst_path, input_dir)
    md = converter.handle(main_html).strip() + "\n"

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(md, encoding="utf-8")


def copy_non_html_files(input_dir: Path, output_dir: Path) -> None:
    for file_path in input_dir.rglob("*"):
        if file_path.is_dir():
            continue
        if file_path.suffix.lower() in {".html", ".htm"}:
            continue
        rel = file_path.relative_to(input_dir)
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Конвертация Confluence HTML-экспорта в Markdown."
    )
    parser.add_argument("--input", required=True, help="Папка с HTML экспортом")
    parser.add_argument("--output", required=True, help="Папка для Markdown")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input not found: {input_dir}")

    converter = make_converter()
    html_map = build_html_map(input_dir, output_dir)
    page_id_map = build_page_id_map(input_dir, html_map)

    for rel, md_path in html_map.items():
        src = input_dir / rel
        convert_html_file(src, md_path, html_map, page_id_map, input_dir, converter)

    copy_non_html_files(input_dir, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
