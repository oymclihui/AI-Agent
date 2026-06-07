"""
Document Loader - supports PDF, DOCX, plain text, and URLs.
Inspired by LangChain's document loaders and Dify's ingestion pipeline.
"""
from typing import Optional
import structlog
from langchain_core.documents import Document

logger = structlog.get_logger(__name__)


class DocumentLoader:
    @staticmethod
    async def load_file(file_path: str, filename: str) -> list[Document]:
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
        logger.info("document_load", filename=filename, type=suffix)

        if suffix == "pdf":
            return await DocumentLoader._load_pdf(file_path, filename)
        elif suffix in ("docx", "doc"):
            return await DocumentLoader._load_docx(file_path, filename)
        elif suffix in ("txt", "md", "rst"):
            return await DocumentLoader._load_text(file_path, filename)
        elif suffix in ("html", "htm"):
            return await DocumentLoader._load_html(file_path, filename)
        else:
            return await DocumentLoader._load_text(file_path, filename)

    @staticmethod
    async def load_url(url: str) -> list[Document]:
        import httpx
        from bs4 import BeautifulSoup

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, follow_redirects=True)

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        return [Document(page_content=text, metadata={"source": url, "type": "url"})]

    @staticmethod
    async def _load_pdf(file_path: str, filename: str) -> list[Document]:
        import pypdf
        docs = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    docs.append(Document(
                        page_content=text,
                        metadata={"source": filename, "page": i + 1, "type": "pdf"},
                    ))
        return docs

    @staticmethod
    async def _load_docx(file_path: str, filename: str) -> list[Document]:
        from docx import Document as DocxDoc
        doc = DocxDoc(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(paragraphs)
        return [Document(
            page_content=full_text,
            metadata={"source": filename, "type": "docx"},
        )]

    @staticmethod
    async def _load_text(file_path: str, filename: str) -> list[Document]:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return [Document(
            page_content=content,
            metadata={"source": filename, "type": "text"},
        )]

    @staticmethod
    async def _load_html(file_path: str, filename: str) -> list[Document]:
        from bs4 import BeautifulSoup
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return [Document(
            page_content=text,
            metadata={"source": filename, "type": "html"},
        )]
