import os
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
        """动态挂载模型引擎"""
        try:
            if mode == "local":
                self.llm = ChatOllama(model=model_name or "qwen2", temperature=0.3)
            else:
                self.llm = ChatOpenAI(
                    model=model_name or "glm-4",
                    openai_api_key=api_key or "EMPTY",
                    openai_api_base=api_base or "https://open.bigmodel.cn/api/paas/v4/",
                    temperature=0.3
                )
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def get_available_sources(self, session_id=None):
        """获取当前可见的文档源"""
        data = self.db.get()
        res = {"public": set(), "private": set()}
        if not data or 'metadatas' not in data: return {"public": [], "private": []}
        for meta in data['metadatas']:
            if not meta: continue
            scope, source = meta.get("scope", ""), meta.get("source", "")
            if scope == "public":
                res["public"].add(source)
            elif session_id and scope == f"session_{session_id}":
                res["private"].add(source)
        return {"public": sorted(list(res["public"])), "private": sorted(list(res["private"]))}

    def change_file_scope(self, filename, old_scope, new_scope):
        """权限流转：修改文档的作用域"""
        data = self.db.get(where={"$and": [{"source": filename}, {"scope": old_scope}]})
        if data and data['ids']:
            new_metas = data['metadatas']
            for m in new_metas: m['scope'] = new_scope
            self.db.update(ids=data['ids'], metadatas=new_metas)
            return True
        return False

    # ==========================================
    # 🗑️ 数据删除内核方法
    # ==========================================
    def delete_document(self, filename, scope):
        """删除指定作用域下的特定文档的所有向量"""
        data = self.db.get(where={"$and": [{"source": filename}, {"scope": scope}]})
        if data and data['ids']:
            self.db.delete(ids=data['ids'])
            return True
        return False

    def delete_session_data(self, session_id):
        """连根拔起：删除某个会话下的所有私有向量数据"""
        data = self.db.get(where={"scope": f"session_{session_id}"})
        if data and data['ids']:
            self.db.delete(ids=data['ids'])
            return True
        return False

    def ask(self, question, selected_sources=None, session_id=None, include_public=True):
        """DFR 空间隔离检索与多模态问答支持"""
        scopes = []
        if include_public: scopes.append({"scope": "public"})
        if session_id: scopes.append({"scope": f"session_{session_id}"})

        filter_dict = {"$or": scopes} if len(scopes) > 1 else (scopes[0] if scopes else None)

        if selected_sources:
            s_filter = {"source": {"$in": selected_sources}} if len(selected_sources) > 1 else {
                "source": selected_sources[0]}
            filter_dict = {"$and": [filter_dict, s_filter]} if filter_dict else s_filter

        retriever = self.db.as_retriever(search_kwargs={"k": 5, "filter": filter_dict})
        docs = retriever.invoke(question)

        if not docs: return "❌ 未检索到相关知识，请调整问题或检查知识库。", []

        ctx, cites = "", []
        for i, d in enumerate(docs):
            src = d.metadata.get('source', '未知')
            cites.append(f"[{i + 1}] 《{src}》")
            ctx += f"\n--- 片段 {i + 1} ---\n{d.page_content}\n"

        # 💡 核心修改：在 System Prompt 植入多模态指令，迫使大模型输出图片链接锚点
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是一个专业助教 CourseRobot。请基于提供的资料片段严谨地回答问题。\n⚠️【核心指令】：如果资料片段中包含图片链接标记（如 ![图表资产](路径)），并且你的回答参考了该段落的内容，请你务必在回答的合适位置原样输出这个图片链接标记，以便向用户展示原图。\n如果资料中没有答案，请明确告知。"),
            ("human", "资料：\n{context}\n\n问题：{question}")
        ])
        chain = prompt | self.llm | StrOutputParser()
        return chain.invoke({"context": ctx, "question": question}), cites