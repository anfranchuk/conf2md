import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import html2text
import requests
from atlassian import Confluence
from bs4 import BeautifulSoup


@dataclass
class PageNode:
    page_id: str
    title: str
    children: List["PageNode"] = field(default_factory=list)
    path: Optional[Path] = None


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9а-яё\-_ ]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text or "page"


def build_tree(confluence: Confluence, page_id: str) -> PageNode:
    page = confluence.get_page_by_id(page_id, expand="title")
    node = PageNode(page_id=str(page["id"]), title=page["title"])
    start = 0
    limit = 50
    while True:
        children = confluence.get_page_child_by_type(
            page_id, type="page", start=start, limit=limit
        )
        results = children.get("results", [])
        for child in results:
            node.children.append(build_tree(confluence, child["id"]))
        if len(results) < limit:
            break
        start += limit
    return node


def assign_paths(node: PageNode, parent_dir: Path, index_name: str) -> None:
    safe = f"{slugify(node.title)}__{node.page_id}"
    node_dir = parent_dir / safe
    node.path = node_dir / index_name
    for child in node.children:
        assign_paths(child, node_dir, index_name)


def collect_nodes(node: PageNode, out: List[PageNode]) -> None:
    out.append(node)
    for child in node.children:
        collect_nodes(child, out)


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


def rewrite_links(
    html: str,
    current_md_path: Path,
    page_id_to_md: Dict[str, Path],
    attachment_dir: Path,
) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def replace_to_relative(target_path: Path) -> str:
        rel = os.path.relpath(target_path, current_md_path.parent)
        return rel.replace("\\", "/")

    for tag in soup.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        url = tag.get(attr)
        if not url:
            continue

        # Internal Confluence page links: ...pageId=12345
        match = re.search(r"[?&]pageId=(\d+)", url)
        if match:
            target_id = match.group(1)
            if target_id in page_id_to_md:
                tag[attr] = replace_to_relative(page_id_to_md[target_id])
            continue

        # Attachment downloads: /download/attachments/{pageId}/file
        attach_match = re.search(r"/download/attachments/(\d+)/([^?]+)", url)
        if attach_match:
            filename = attach_match.group(2)
            tag[attr] = replace_to_relative(attachment_dir / filename)

    return str(soup)


def download_attachments(
    confluence: Confluence,
    session: requests.Session,
    base_url: str,
    page_id: str,
    attachment_dir: Path,
) -> None:
    attachment_dir.mkdir(parents=True, exist_ok=True)
    start = 0
    limit = 100
    while True:
        data = confluence.get_page_attachments(page_id, start=start, limit=limit)
        results = data.get("results", [])
        for att in results:
            download = att.get("_links", {}).get("download")
            if not download:
                continue
            url = f"{base_url}{download}"
            filename = att.get("title") or Path(download).name
            target = attachment_dir / filename
            if target.exists():
                continue
            resp = session.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(target, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        if len(results) < limit:
            break
        start += limit


def export_page(
    confluence: Confluence,
    session: requests.Session,
    base_url: str,
    node: PageNode,
    page_id_to_md: Dict[str, Path],
    converter: html2text.HTML2Text,
    index_name: str,
) -> None:
    assert node.path is not None
    page = confluence.get_page_by_id(
        node.page_id, expand="body.view,body.storage,version"
    )
    html = page.get("body", {}).get("view", {}).get("value")
    if not html:
        html = page.get("body", {}).get("storage", {}).get("value", "")

    page_dir = node.path.parent
    attachment_dir = page_dir / "attachments"
    download_attachments(confluence, session, base_url, node.page_id, attachment_dir)

    html = rewrite_links(html, node.path, page_id_to_md, attachment_dir)
    md = converter.handle(html).strip() + "\n"

    page_dir.mkdir(parents=True, exist_ok=True)
    with open(node.path, "w", encoding="utf-8") as f:
        f.write(f"# {node.title}\n\n")
        f.write(md)

    # Add a simple local index if page has children
    if node.children:
        index_path = page_dir / "children.md"
        lines = ["# Подстраницы\n"]
        for child in node.children:
            child_md = page_id_to_md[child.page_id]
            rel = os.path.relpath(child_md, page_dir).replace("\\", "/")
            lines.append(f"- [{child.title}]({rel})")
        lines.append("")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Экспорт страницы Confluence и всех подстраниц в Markdown."
    )
    parser.add_argument("--url", required=True, help="Базовый URL Confluence")
    parser.add_argument("--username", required=True, help="Логин")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument("--page-id", required=True, help="ID страницы")
    parser.add_argument("--out", required=True, help="Папка вывода")
    parser.add_argument(
        "--index-name",
        default="index.md",
        help="Имя файла страницы в папке",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Проверять SSL сертификаты",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_url = args.url.rstrip("/")

    confluence = Confluence(
        url=base_url,
        username=args.username,
        password=args.password,
        cloud=False,
        verify_ssl=args.verify_ssl,
    )

    session = requests.Session()
    session.auth = (args.username, args.password)
    session.verify = args.verify_ssl

    root = build_tree(confluence, args.page_id)
    out_dir = Path(args.out).resolve()
    assign_paths(root, out_dir, args.index_name)

    nodes: List[PageNode] = []
    collect_nodes(root, nodes)
    page_id_to_md = {n.page_id: n.path for n in nodes if n.path is not None}

    converter = make_converter()
    for node in nodes:
        export_page(
            confluence,
            session,
            base_url,
            node,
            page_id_to_md,
            converter,
            args.index_name,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
