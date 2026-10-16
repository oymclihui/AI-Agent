from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


class DocumentChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.parent_size = max(chunk_size, 400)
        self.child_size = max(220, min(400, self.parent_size // 3))
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.parent_size,
            chunk_overlap=min(chunk_overlap, 200),
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.child_size,
            chunk_overlap=40,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )

    def split(self, documents: list[Document]) -> list[Document]:
        parents, children = self.split_parent_child(documents)
        return children or parents

    def split_parent_child(self, documents: list[Document]) -> tuple[list[Document], list[Document]]:
        parents = self.parent_splitter.split_documents(documents)
        children: list[Document] = []
        for parent_index, parent in enumerate(parents):
            source = parent.metadata.get("source", "")
            parent.metadata["role"] = "parent"
            parent.metadata["chunk_index"] = parent_index
            parent.metadata["parent_index"] = parent_index
            parent.metadata["source"] = source
            pieces = self.child_splitter.split_documents([parent]) or [parent]
            for child_index, child in enumerate(pieces):
                child.metadata["role"] = "child"
                child.metadata["parent_index"] = parent_index
                child.metadata["chunk_index"] = parent_index * 1000 + child_index
                child.metadata["source"] = source
                children.append(child)
        return parents, children
