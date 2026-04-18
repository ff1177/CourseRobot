import os
import fitz  # PyMuPDF
import pandas as pd
from docx import Document as DocxDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document


def extract_text_from_file(file_path, file_name):
    """根据文件后缀名，自动选择合适的解析器提取纯文本"""
    ext = os.path.splitext(file_name)[1].lower()
    full_text = ""

    try:
        if ext == '.pdf':
            doc = fitz.open(file_path)
            for page_num in range(len(doc)):
                page_text = doc[page_num].get_text()
                if page_text.strip():
                    full_text += f"\n## 第 {page_num + 1} 页\n" + page_text
            doc.close()

        elif ext == '.docx':
            doc = DocxDocument(file_path)
            for i, para in enumerate(doc.paragraphs):
                if para.text.strip():
                    full_text += f"{para.text}\n"

        elif ext in ['.xlsx', '.xls', '.csv']:
            if ext == '.csv':
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            # 将表格转换为 Markdown 格式文本，大模型最容易看懂
            full_text = df.to_markdown(index=False)

        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                full_text = f.read()
        else:
            raise ValueError(f"暂不支持该文件格式: {ext}")

    except Exception as e:
        print(f"解析 {file_name} 时发生错误: {e}")
        return ""

    return full_text


def process_and_ingest(uploaded_file, scope_tag, db_dir="chroma_db"):
    try:
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, uploaded_file.name)

        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # 1. 调用万能文本提取器
        full_text = extract_text_from_file(file_path, uploaded_file.name)

        if not full_text.strip():
            return False

        docs = [Document(
            page_content=full_text,
            metadata={"source": uploaded_file.name, "scope": scope_tag}
        )]

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
        splits = text_splitter.split_documents(docs)

        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        Chroma.from_documents(documents=splits, embedding=embeddings, persist_directory=db_dir)

        if os.path.exists(file_path):
            os.remove(file_path)
        return True
    except Exception as e:
        print(f"文档入库失败: {e}")
        return False
