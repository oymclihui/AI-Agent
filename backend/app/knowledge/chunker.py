from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


class DocumentChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )

    def split(self, documents: list[Document]) -> list[Document]:
        chunks = self.splitter.split_documents(documents)
        # Enrich chunk metadata with index
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
        return chunks
