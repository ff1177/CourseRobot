import os
import re
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.chat_models import ChatOllama
from langchain_openai import ChatOpenAI


class DFR_RAG_Agent:
    def __init__(self, db_dir="chroma_db"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        self.embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-zh-v1.5")
        self.db = Chroma(persist_directory=db_dir, embedding_function=self.embeddings)
        self.llm = None

    def set_model(self, mode, model_name=None, api_key=None, api_base=None):
        """
        全动态模型挂载器。接收用户从前端传来的自定义配置。
        """
        try:
            if mode == "local":
                # 用户填什么名字，Ollama就调什么模型
                target_model = model_name if model_name else "qwen2"
                self.llm = ChatOllama(model=target_model, temperature=0.3)
            else:
                # BYOK (Bring Your Own Key) 模式，兼容所有 OpenAI 格式的接口
                target_model = model_name if model_name else "glm-4"
                target_key = api_key if api_key else "EMPTY"
                target_base = api_base if api_base else "https://open.bigmodel.cn/api/paas/v4/"

                self.llm = ChatOpenAI(
                    temperature=0.3,
                    model=target_model,
                    openai_api_key=target_key,
                    openai_api_base=target_base
                )
            return True, "模型初始化成功"
        except Exception as e:
            return False, str(e)

    # ...(下面保留原有的 get_available_sources, change_file_scope, delete_session_data, ask 方法，无需修改)
    def get_available_sources(self, session_id=None):
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
                result["private"].add(source)
        return {"public": sorted(list(result["public"])), "private": sorted(list(result["private"]))}

    def change_file_scope(self, filename, old_scope, new_scope):
        try:
            data = self.db.get(where={"$and": [{"source": filename}, {"scope": old_scope}]})
            if data and data['ids']:
                metadatas = data['metadatas']
                for meta in metadatas: meta['scope'] = new_scope
                self.db.update(ids=data['ids'], metadatas=metadatas)
                return True
            return False
        except:
            return False

    def delete_session_data(self, session_id):
        try:
            data = self.db.get(where={"scope": f"session_{session_id}"})
            if data and data['ids']: self.db.delete(ids=data['ids'])
        except:
            pass

    def ask(self, question, selected_sources=None, session_id=None, include_public=True):
        scope_filters = []
        if include_public: scope_filters.append({"scope": "public"})
        if session_id: scope_filters.append({"scope": f"session_{session_id}"})

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

        if not docs: return "❌ 未找到相关信息。", []

        context_text = ""
        citations = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get('source', '未知文档')
            scope_label = "公共库" if doc.metadata.get('scope') == "public" else "对话专属"
            citations.append(f"[{i + 1}] 《{source}》 ({scope_label})")
            context_text += f"\n--- 资料片段 {i + 1} ---\n{doc.page_content}\n"

        prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个专业的学术助教。请基于参考资料回答问题。"),
            ("human", "参考资料：\n{context}\n\n问题：{question}")
        ])

        chain = prompt | self.llm | StrOutputParser()
        answer = chain.invoke({"context": context_text, "question": question})
        return answer, citations


