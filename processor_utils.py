import os
import fitz  # PyMuPDF
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document


def process_and_ingest(uploaded_file, scope_tag, db_dir="chroma_db"):
    """
    Streamlit 专用的无头(Headless)文档处理管线
    将接收到的文件直接解析并打上所属空间的标签存入数据库。
    """
    try:
        # 1. 临时保存上传的文件流
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, uploaded_file.name)

        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # 2. 文本提取 (此处采用稳定轻量的 fitz 提取)
        # 注意：这里我们提取纯文本。你之前在终端跑的 final_knowledge_base.md
        # 属于"公共库(预处理)"，网页端的上传相当于用户的"临时加餐"。
        doc = fitz.open(file_path)
        full_text = ""
        for page_num in range(len(doc)):
            page_text = doc[page_num].get_text()
            if page_text.strip():
                # 加入页码锚点供正则追踪
                full_text += f"\n## 第 {page_num + 1} 页\n" + page_text
        doc.close()

        if not full_text.strip():
            return False

        # 3. 构造 LangChain Document 并注入【核心空间标签 Scope】
        docs = [Document(
            page_content=full_text,
            metadata={
                "source": uploaded_file.name,
                "scope": scope_tag  # <- 这个标签决定了它是属于哪个对话的！
            }
        )]

        # 4. 语义切片
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
        splits = text_splitter.split_documents(docs)

        # 5. 向量化并合并入库
        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        Chroma.from_documents(documents=splits, embedding=embeddings, persist_directory=db_dir)

        # 清理临时文件
        if os.path.exists(file_path):
            os.remove(file_path)

        return True
    except Exception as e:
        print(f"文档处理桥梁报错: {e}")
        return False