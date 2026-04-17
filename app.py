import streamlit as st
import os
import uuid
import json
from chat_agent import DFR_RAG_Agent
from processor_utils import process_and_ingest

# ==========================================
# 0. 页面配置与基础环境
# ==========================================
st.set_page_config(page_title="CourseRobot 智能中枢", layout="wide", page_icon="🎓")

# ==========================================
# 1. 拦截器：登录认证系统
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.write("")
        st.write("")
        st.write("")
        st.title("🎓 CourseRobot")
        st.caption("基于 DFR-RAG 的校园大语言模型智能问答系统")
        st.info("💡 测试账号：\n- 管理员：admin / admin\n- 普通用户：user / 123456")

        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submit = st.form_submit_button("登录系统", type="primary", use_container_width=True)

            if submit:
                if username == "admin" and password == "admin":
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = "admin"
                    st.rerun()
                elif username == "user" and password == "123456":
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = "user"
                    st.rerun()
                else:
                    st.error("账号或密码错误！请检查后重试。")
    st.stop()


# ==========================================
# 2. 本地持久化存储机制
# ==========================================
def get_session_file():
    return f"course_robot_sessions_{st.session_state.username}.json"


def load_sessions():
    file_path = get_session_file()
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "chats" in data and "active_chat" in data:
                    # 兼容旧版本：为所有已存在的对话补充 selected_docs 字段
                    for cid, cdata in data["chats"].items():
                        if "selected_docs" not in cdata:
                            cdata["selected_docs"] = []
                    return data["chats"], data["active_chat"]
        except Exception:
            pass
    return None, None


def save_sessions():
    file_path = get_session_file()
    data = {
        "chats": st.session_state.chats,
        "active_chat": st.session_state.active_chat
    }
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


# ==========================================
# 3. 初始化 Session 状态
# ==========================================
if "agent" not in st.session_state:
    st.session_state.agent = DFR_RAG_Agent()

if "chats" not in st.session_state:
    loaded_chats, loaded_active = load_sessions()
    if loaded_chats and loaded_active:
        st.session_state.chats = loaded_chats
        st.session_state.active_chat = loaded_active
    else:
        first_id = str(uuid.uuid4())
        # 【核心修复】：为每个新对话加上专属的 selected_docs 记忆区
        st.session_state.chats = {first_id: {"name": "新会话", "messages": [], "selected_docs": []}}
        st.session_state.active_chat = first_id
        save_sessions()

if "current_page" not in st.session_state:
    st.session_state.current_page = "💬 智能对话"

if "chat_uploader_key" not in st.session_state:
    st.session_state.chat_uploader_key = str(uuid.uuid4())
if "global_uploader_key" not in st.session_state:
    st.session_state.global_uploader_key = str(uuid.uuid4())

if "show_confirm_dialog" not in st.session_state:
    st.session_state.show_confirm_dialog = False

active_id = st.session_state.active_chat

# ==========================================
# 4. 侧边栏：全局导航与无缝跳转
# ==========================================
with st.sidebar:
    st.title("🤖 CourseRobot")

    role_name = "管理员" if st.session_state.role == "admin" else "用户"
    st.info(f"👤 {st.session_state.username} ({role_name})")
    if st.button("🚪 退出登录", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.divider()

    st.subheader("📌 页面导航")
    nav_options = ["💬 智能对话", "🗄️ 知识库管理"]
    for nav in nav_options:
        label = f"▶ {nav}" if st.session_state.current_page == nav else nav
        if st.button(label, key=f"nav_{nav}", use_container_width=True):
            st.session_state.current_page = nav
            st.rerun()

    st.divider()

    st.subheader("💬 会话列表")
    if st.button("➕ 开启新对话", use_container_width=True):
        new_id = str(uuid.uuid4())
        st.session_state.chats[new_id] = {"name": f"新会话", "messages": [], "selected_docs": []}
        st.session_state.active_chat = new_id
        st.session_state.current_page = "💬 智能对话"
        save_sessions()
        st.rerun()

    for cid, chat in list(st.session_state.chats.items()):
        btn_label = f"👉 {chat['name']}" if cid == active_id else chat['name']
        if st.button(btn_label, key=f"btn_{cid}", use_container_width=True):
            st.session_state.active_chat = cid
            st.session_state.current_page = "💬 智能对话"
            save_sessions()
            st.rerun()

    st.divider()
    if st.button("🗑️ 删除当前会话及专属文件", type="primary", use_container_width=True):
        if len(st.session_state.chats) > 1:
            st.session_state.agent.delete_session_data(active_id)
            del st.session_state.chats[active_id]
            st.session_state.active_chat = list(st.session_state.chats.keys())[0]
            save_sessions()
            st.success("清理完毕！")
            st.rerun()
        else:
            st.error("至少保留一个会话！")

# ==========================================
# 5. 拦截器弹窗定义
# ==========================================
real_pub_key = f"real_pub_{active_id}"
widget_pub_key = f"widget_pub_{active_id}"
selection_key = f"sel_docs_{active_id}"

if real_pub_key not in st.session_state:
    st.session_state[real_pub_key] = True


@st.dialog("⚠️ 确认操作")
def confirm_disable_pub():
    st.warning("您当前已选中了部分公共库文件，强行关闭将自动取消选中它们。")
    st.write("是否继续关闭公共库？")
    col1, col2 = st.columns(2)
    if col1.button("确认关闭", type="primary", use_container_width=True):
        st.session_state[real_pub_key] = False
        st.session_state.show_confirm_dialog = False

        # 关闭公共库时，清洗掉已选择文档中的公共文件记忆
        chat_data = st.session_state.chats[active_id]
        chat_data["selected_docs"] = [d for d in chat_data.get("selected_docs", []) if not d.startswith("🌐")]
        save_sessions()

        st.rerun()
    if col2.button("放弃操作", use_container_width=True):
        st.session_state.show_confirm_dialog = False
        st.rerun()


if st.session_state.show_confirm_dialog:
    confirm_disable_pub()


def toggle_pub():
    new_val = st.session_state[widget_pub_key]
    if not new_val:
        current_selections = st.session_state.chats[active_id].get("selected_docs", [])
        has_pub_selected = any(d.startswith("🌐") for d in current_selections)
        if has_pub_selected:
            st.session_state.show_confirm_dialog = True
        else:
            st.session_state[real_pub_key] = False
            st.toast("🔒 已关闭关联公共库！", icon="✅")
    else:
        st.session_state[real_pub_key] = True
        st.toast("🌐 已开启关联公共库！", icon="✅")


if st.session_state.show_confirm_dialog:
    st.session_state[widget_pub_key] = True
else:
    st.session_state[widget_pub_key] = st.session_state[real_pub_key]

# ==========================================
# 6. 页面路由分发
# ==========================================
page = st.session_state.current_page

# ----------------------------------------
# 页面 A：智能对话
# ----------------------------------------
if page == "💬 智能对话":
    chat_data = st.session_state.chats[active_id]

    # 兜底机制：防止旧数据没有 selected_docs 字段报错
    if "selected_docs" not in chat_data:
        chat_data["selected_docs"] = []

    cols = st.columns([1, 2, 1])
    with cols[0]:
        model_choice = st.selectbox(
            "🧠 推理引擎",
            ["云端 (智谱 API)", "本地 (Ollama)"],
            index=0 if st.session_state.agent.llm and st.session_state.agent.llm.__class__.__name__ == "ChatOpenAI" else 1
        )
        if model_choice.startswith("本地"):
            st.session_state.agent.set_model("1")
        else:
            st.session_state.agent.set_model("2")

    with cols[1]:
        docs_dict = st.session_state.agent.get_available_sources(session_id=active_id)
        pub_docs = [f"🌐 {d}" for d in docs_dict["public"]]
        priv_docs = [f"🔒 {d}" for d in docs_dict["private"]]

        available_for_search = pub_docs + priv_docs if st.session_state[real_pub_key] else priv_docs

        # 【核心修复】：从本地提取当前会话的“文档记忆”，并过滤掉已不在选项中的过时文件
        current_defaults = [d for d in chat_data["selected_docs"] if d in available_for_search]

        selected_docs_display = st.multiselect(
            "📚 提问范围 (留空则搜索全部)",
            available_for_search,
            default=current_defaults,
            key=selection_key
        )

        # 如果用户在界面上的选择发生了变化，实时更新记忆并落盘
        if selected_docs_display != chat_data["selected_docs"]:
            chat_data["selected_docs"] = selected_docs_display
            save_sessions()

        clean_selected_docs = [d[2:] for d in selected_docs_display]

    with cols[2]:
        st.write(" ")
        st.write(" ")
        st.checkbox("🔍 关联公共库", key=widget_pub_key, on_change=toggle_pub)

    st.markdown("---")

    # 【UI】渲染历史消息
    for msg in chat_data["messages"]:
        avatar = "🧑‍🎓" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # 【防中断机制】：检查是否有未被回答的用户提问
    last_is_user = len(chat_data["messages"]) > 0 and chat_data["messages"][-1]["role"] == "user"

    bottom_cols = st.columns([1, 15])

    with bottom_cols[0]:
        with st.popover("📎"):
            st.write("### 批量附加文件")
            st.caption("文件将仅供当前对话引用")
            temp_files = st.file_uploader(
                "选择一个或多个 PDF",
                type="pdf",
                accept_multiple_files=True,
                key=st.session_state.chat_uploader_key
            )

            if temp_files and st.button("开始批量解析入库"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                success_count = 0

                for i, file in enumerate(temp_files):
                    status_text.text(f"正在处理 ({i + 1}/{len(temp_files)}): {file.name}")
                    if process_and_ingest(file, f"session_{active_id}"):
                        success_count += 1
                    progress_bar.progress((i + 1) / len(temp_files))

                status_text.text(f"✅ 成功导入 {success_count} 份私有文档！")
                st.session_state.chat_uploader_key = str(uuid.uuid4())
                st.rerun()

    with bottom_cols[1]:
        prompt = st.chat_input("发送消息给 CourseRobot...")
        retry_container = st.empty()
        retry_button = False

        # 如果上一次提问被切换页面强制中断了，显示补救按钮
        if last_is_user and not prompt:
            with retry_container.container():
                st.warning("⚠️ 检测到您刚才的提问被切换页面强制中断了，AI 尚未完成回答。")
                # 使用靠右对齐的按钮
                col_btn = st.columns([8, 2])
                with col_btn[1]:
                    retry_button = st.button("🔄 重新继续回答", use_container_width=True)

        if prompt or retry_button:
            # 判断是新提问还是重试提问
            if retry_button:
                retry_container.empty()  # 清除提示和按钮，保持界面清爽
                current_prompt = chat_data["messages"][-1]["content"]  # 提取上次被中断的问题
            else:
                current_prompt = prompt
                chat_data["messages"].append({"role": "user", "content": current_prompt})

                # 新会话的 AI 自动命名逻辑
                if len(chat_data["messages"]) == 1 or chat_data["name"] == "新会话":
                    try:
                        if st.session_state.agent.llm:
                            summary_prompt = f"请提取以下文本的核心主题作为标题。要求：绝对不要超过10个字，不要标点符号和书名号，直接输出文字：\n{current_prompt}"
                            res = st.session_state.agent.llm.invoke(summary_prompt)
                            if res and getattr(res, 'content', None):
                                new_title = res.content.strip().replace("\"", "").replace("《", "").replace("》", "")[:10]
                                if new_title:
                                    chat_data["name"] = new_title
                    except Exception:
                        pass

                save_sessions()
                with st.chat_message("user", avatar="🧑‍🎓"):
                    st.markdown(current_prompt)

            with st.chat_message("assistant", avatar="🤖"):
                if not st.session_state.agent.llm:
                    st.error("⚠️ 模型未初始化！请确保左上方推理引擎已选择正确。")
                else:
                    with st.spinner("思考中..."):
                        # 【防撞气囊】：捕获本地 Ollama 的一切异常
                        try:
                            ans, cites = st.session_state.agent.ask(
                                current_prompt,
                                selected_sources=clean_selected_docs,
                                session_id=active_id,
                                include_public=st.session_state[real_pub_key]
                            )
                            full_ans = ans + "\n\n**📍 知识溯源：**\n"
                            for c in cites:
                                full_ans += f"- {c}\n"
                            st.markdown(full_ans)
                            chat_data["messages"].append({"role": "assistant", "content": full_ans})
                            save_sessions()
                        except Exception as e:
                            st.error(
                                f"🚨 **大模型请求失败！** \n\n**错误详情**：`{e}`\n\n**诊断建议**：\n1. 如果在使用本地模型，请确保终端黑框框里正在运行 `ollama serve`。\n2. 请确认 `chat_agent.py` 里填写的 `LOCAL_MODEL_NAME` (当前为 `{st.session_state.agent.llm.model}`) 是你电脑里真实安装的模型名称。")

# ----------------------------------------
# 页面 B：知识库管理
# ----------------------------------------
elif page == "🗄️ 知识库管理":
    st.title("🗄️ 知识库管理中枢")

    # ================== 【管理员视图】 ==================
    if st.session_state.role == "admin":
        st.success("👑 您拥有全局最高权限，可管理公共知识库及权限流转。")
        col_upload, col_transfer = st.columns(2)

        with col_upload:
            st.subheader("📥 注入公共知识 (全局可见)")
            global_files = st.file_uploader(
                "选择底层基础文件 (PDF)",
                type="pdf",
                accept_multiple_files=True,
                key=st.session_state.global_uploader_key
            )

            if global_files and st.button("一键执行全局入库", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                success_count = 0
                for i, file in enumerate(global_files):
                    status_text.text(f"🚀 全局入库中 ({i + 1}/{len(global_files)}): {file.name}")
                    if process_and_ingest(file, "public"):
                        success_count += 1
                    progress_bar.progress((i + 1) / len(global_files))

                st.success(f"✨ 处理完成！共 {success_count} 个文件存入公共知识库。")
                st.session_state.global_uploader_key = str(uuid.uuid4())
                st.rerun()

        with col_transfer:
            st.subheader("🔁 权限流转控制")
            docs_dict = st.session_state.agent.get_available_sources(session_id=active_id)
            pub_docs = [f"🌐 {d}" for d in docs_dict["public"]]
            priv_docs = [f"🔒 {d}" for d in docs_dict["private"]]

            if pub_docs or priv_docs:
                transfer_file_display = st.selectbox("选择要流转的文件", pub_docs + priv_docs)
                clean_filename = transfer_file_display[2:]
                current_is_pub = transfer_file_display.startswith("🌐")

                old_scope = "public" if current_is_pub else f"session_{active_id}"

                if current_is_pub:
                    target_session = st.selectbox(
                        "👇 请选择要转入哪个具体的私有会话：",
                        options=list(st.session_state.chats.keys()),
                        format_func=lambda x: st.session_state.chats[x]['name']
                    )
                    new_scope = f"session_{target_session}"
                    label = "⬇️ 降级为指定会话私有"
                else:
                    new_scope = "public"
                    label = "⬆️ 提拔为全局公共文件"

                if st.button(label, use_container_width=True):
                    if st.session_state.agent.change_file_scope(clean_filename, old_scope, new_scope):
                        st.success("权限流转成功！")
                        st.rerun()
            else:
                st.warning("当前空间暂无文件。")

    # ================== 【普通用户视图】 ==================
    else:
        st.info("👤 作为普通用户，您仅可管理自己的私有知识资产。")
        col_upload, col_transfer = st.columns(2)

        with col_upload:
            st.subheader("📥 批量上传私有知识")
            target_upload_session = st.selectbox(
                "请选择要挂载知识的会话：",
                options=list(st.session_state.chats.keys()),
                format_func=lambda x: st.session_state.chats[x]['name']
            )
            priv_files = st.file_uploader(
                "选择 PDF 文件 (支持多选)",
                type="pdf",
                accept_multiple_files=True,
                key=st.session_state.global_uploader_key
            )
            if priv_files and st.button("执行入库", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                success_count = 0
                for i, file in enumerate(priv_files):
                    status_text.text(f"🚀 私有入库中 ({i + 1}/{len(priv_files)}): {file.name}")
                    if process_and_ingest(file, f"session_{target_upload_session}"):
                        success_count += 1
                    progress_bar.progress((i + 1) / len(priv_files))

                st.success(f"✨ 成功导入 {success_count} 份文档！")
                st.session_state.global_uploader_key = str(uuid.uuid4())
                st.rerun()

        with col_transfer:
            st.subheader("🔁 私有文件漂移")
            st.caption("您可以将在某会对话上传的文件，漂移转移至您的其他会话。")

            docs_dict = st.session_state.agent.get_available_sources(session_id=active_id)
            priv_docs = [f"🔒 {d}" for d in docs_dict["private"]]

            if priv_docs:
                transfer_file_display = st.selectbox(f"当前【{st.session_state.chats[active_id]['name']}】的私有文件：",
                                                     priv_docs)
                clean_filename = transfer_file_display[2:]
                old_scope = f"session_{active_id}"

                target_drift_session = st.selectbox(
                    "👇 请选择要漂移至哪个目标会话：",
                    options=[k for k in st.session_state.chats.keys() if k != active_id],
                    format_func=lambda x: st.session_state.chats[x]['name']
                )

                if target_drift_session:
                    if st.button("➡️ 执行文件转移", use_container_width=True):
                        new_scope = f"session_{target_drift_session}"
                        if st.session_state.agent.change_file_scope(clean_filename, old_scope, new_scope):
                            st.success("私有文件流转成功！")
                            st.rerun()
                else:
                    st.warning("您目前只有一个会话，请先点击左侧【开启新对话】后再尝试转移功能。")
            else:
                st.info("当前会话无私有文件可供转移。")