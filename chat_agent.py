import os
import re
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI

# ==========================================
# ⚙️ 配置区
# ==========================================
import os
API_KEY = os.environ.get("ZHIPU_API_KEY", "b1bc596187c743d99f3d539c6822d33a.BUmhyOnaNqiYKggm")
API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LOCAL_MODEL_NAME = "my-qwen"


class DFR_RAG_Agent:
    def __init__(self, db_dir="chroma_db"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self.db = Chroma(persist_directory=db_dir, embedding_function=self.embeddings)
        self.llm = None

    def set_model(self, mode):
        """动态切换大模型路由"""
        if mode == "1":
            self.llm = ChatOllama(model=LOCAL_MODEL_NAME, temperature=0.3)
        else:
            self.llm = ChatOpenAI(
                temperature=0.3,
                model="glm-4",
                openai_api_key=API_KEY,
                openai_api_base=API_BASE_URL
            )

    def get_available_sources(self, session_id=None):
        """扫描数据库，严格分离公共库和私有库，修复越权漏洞"""
        data = self.db.get()
        result = {"public": set(), "private": set()}
        if not data or 'metadatas' not in data:
            return {"public": [], "private": []}

        for meta in data['metadatas']:
            if not meta: continue
            scope = meta.get("scope", "")
            source = meta.get("source", "")

            if scope == "public":
                result["public"].add(source)
            elif session_id and scope == f"session_{session_id}":
                # 只有匹配当前 session_id 的数据才会进入私有列表
                result["private"].add(source)

        return {
            "public": sorted(list(result["public"])),
            "private": sorted(list(result["private"]))
        }

    def change_file_scope(self, filename, old_scope, new_scope):
        """文件权限流转：将文件在私有库和公共库之间互相转移"""
        try:
            # 精准定位文件名和旧权限标签
            data = self.db.get(where={"$and": [{"source": filename}, {"scope": old_scope}]})
            if data and data['ids']:
                metadatas = data['metadatas']
                for meta in metadatas:
                    meta['scope'] = new_scope
                # 更新 Chroma 数据库中的元数据
                self.db.update(ids=data['ids'], metadatas=metadatas)
                return True
            return False
        except Exception as e:
            print(f"权限修改失败: {e}")
            return False

    def delete_session_data(self, session_id):
        """彻底删除当前对话上传的所有专属数据"""
        try:
            data = self.db.get(where={"scope": f"session_{session_id}"})
            if data and data['ids']:
                self.db.delete(ids=data['ids'])
                print(f"🗑️ 已成功清理会话 {session_id} 的专属数据")
        except Exception as e:
            print(f"清理数据失败: {e}")

    def ask(self, question, selected_sources=None, session_id=None, include_public=True):
        """支持空间隔离(Scope)的增强版检索"""
        scope_filters = []
        if include_public:
            scope_filters.append({"scope": "public"})
        if session_id:
            scope_filters.append({"scope": f"session_{session_id}"})

        filter_dict = None
        if len(scope_filters) == 1:
            filter_dict = scope_filters[0]
        elif len(scope_filters) > 1:
            filter_dict = {"$or": scope_filters}

        if selected_sources:
            source_filter = {"source": {"$in": selected_sources}} if len(selected_sources) > 1 else {
                "source": selected_sources[0]}
            if filter_dict:
                filter_dict = {"$and": [filter_dict, source_filter]}
            else:
                filter_dict = source_filter

        retriever = self.db.as_retriever(search_kwargs={"k": 4, "filter": filter_dict})
        docs = retriever.invoke(question)

        if not docs:
            return "❌ 在当前的知识空间内，我没能找到与你问题相关的信息。请检查一下检索范围哦。", []

        context_text = ""
        citations = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get('source', '未知文档')
            scope = doc.metadata.get('scope', 'public')
            scope_label = "公共库" if scope == "public" else "对话专属"

            page_info = "未知页码"
            page_match = re.search(r'第 (\d+) 页', doc.page_content)
            if page_match:
                page_info = f"第 {page_match.group(1)} 页"

            citations.append(f"[{i + 1}] 《{source}》 ({scope_label}) - {page_info}")
            context_text += f"\n--- 资料片段 {i + 1} ---\n{doc.page_content}\n"

        # 【重点更新】通过 Prompt 让大模型像朋友一样与你对话
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个亲切、专业的校园学术助教。请基于参考资料与用户进行自然流畅的对话。
            要求：
            1. 回答内容必须严格基于参考资料，不可捏造。
            2. 如果引用了特定片段，请在句末用数字标注，如 [1]。
            3. 采用“第一人称（我）”和“第二人称（你/您）”的拟人化交流形式，语气要像学长或导师一样，拉近与用户的距离。"""),
            ("human", "参考资料：\n{context}\n\n问题：{question}")
        ])

        chain = prompt | self.llm | StrOutputParser()
        answer = chain.invoke({"context": context_text, "question": question})

        return answer, citations