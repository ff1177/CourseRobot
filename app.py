# =================================================================
# ⚠️ 核心兼容性补丁：必须在所有 import 之前执行
# 解决 ChromaDB 在 Streamlit Cloud (Linux) 环境下 SQLite 版本过低的问题
# =================================================================
import sys
import os

# 检查运行环境，非 Windows 系统（即 Streamlit Cloud）强制使用 pysqlite3
if os.name != 'nt':
    try:
        import pysqlite3

        sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
    except ImportError:
        # 如果环境中没装，则跳过（要求在 requirements.txt 中包含 pysqlite3-binary）
        pass

# =================================================================
# 正常库导入
# =================================================================
import streamlit as st
import uuid
import json
import time
from chat_agent import DFR_RAG_Agent
from processor_utils import process_and_ingest

# --- 基础配置与样式定义 ---
st.set_page_config(
    page_title="CourseRobot 智能中枢",
    layout="wide",
    page_icon="🎓",
    initial_sidebar_state="expanded"
)

# 全局支持的万能格式列表
SUPPORTED_FORMATS = ["pdf", "docx", "txt", "xlsx", "csv"]

# =================================================================
# 1. 登录与身份验证系统 (Guard)
# =================================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    _, col_login, _ = st.columns([1, 1.5, 1])
    with col_login:
        st.write("")
        st.write("")
        st.title("🎓 CourseRobot 登录")
        st.caption("基于 DFR-RAG 的学术知识库管理系统")
        st.info("💡 演示账号：\n- 管理员：admin / admin\n- 普通用户：user / 123456")

        with st.form("login_gate"):
            username = st.text_input("用户名", placeholder="请输入账号")
            password = st.text_input("密码", type="password", placeholder="请输入密码")
            submit = st.form_submit_button("进入智能中枢", type="primary", use_container_width=True)

            if submit:
                if (username == "admin" and password == "admin") or \
                        (username == "user" and password == "123456"):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.session_state.role = "admin" if username == "admin" else "user"
                    st.toast(f"欢迎回来，{username}！", icon="👋")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ 凭证校验失败，请检查账号密码。")
    st.stop()


# =================================================================
# 2. 持久化存储与记忆唤醒逻辑 (多用户隔离)
# =================================================================
def get_memory_file():
    return f"course_robot_sessions_{st.session_state.username}.json"


def save_to_memory():
    """将对话记录、勾选状态和引擎配置同步到本地磁盘"""
    data = {
        "chats": st.session_state.chats,
        "active_chat": st.session_state.active_chat,
        "ai_config": st.session_state.ai_config
    }
    with open(get_memory_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_from_memory():
    """从本地磁盘恢复所有记忆状态"""
    path = get_memory_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


# =================================================================
# 3. 初始化全局状态引擎与【智谱 AI 默认挂载】
# =================================================================
if "agent" not in st.session_state:
    st.session_state.agent = DFR_RAG_Agent()


# 💡 核心：确保大模型就绪（仅在必要时重载）
def ensure_engine_ready():
    cfg = st.session_state.ai_config
    st.session_state.agent.set_model(
        cfg["mode"],
        cfg["local_name"] if cfg["mode"] == "local" else cfg["cloud_model"],
        cfg["cloud_key"],
        cfg["cloud_base"]
    )


if "chats" not in st.session_state:
    mem_data = load_from_memory()

    # --- ✨ 默认初始化为智谱 AI 配置 (开箱即用) ---
    st.session_state.ai_config = mem_data.get("ai_config", {
        "mode": "cloud",
        "cloud_model": "glm-4",
        "cloud_base": "https://open.bigmodel.cn/api/paas/v4/",
        "cloud_key": "",  # 此处建议用户手动填入或从环境变量读取
        "local_name": "qwen2"
    })

    if "chats" in mem_data and "active_chat" in mem_data:
        st.session_state.chats = mem_data["chats"]
        st.session_state.active_chat = mem_data["active_chat"]
    else:
        init_id = str(uuid.uuid4())
        st.session_state.chats = {init_id: {"name": "新会话", "messages": [], "selected_docs": []}}
        st.session_state.active_chat = init_id
        save_to_memory()

    # 登录即自动挂载默认引擎
    ensure_engine_ready()

if "current_page" not in st.session_state:
    st.session_state.current_page = "💬 智能对话"

# 动态 Key 用于清空文件上传框
if "chat_up_key" not in st.session_state: st.session_state.chat_up_key = str(uuid.uuid4())
if "glob_up_key" not in st.session_state: st.session_state.glob_up_key = str(uuid.uuid4())

active_id = st.session_state.active_chat
chat_data = st.session_state.chats[active_id]

# =================================================================
# 4. 侧边栏：多对话管理、BYOK 设置与高级操作
# =================================================================
with st.sidebar:
    st.title("🤖 CourseRobot")
    user_label = "👑 管理员" if st.session_state.role == "admin" else "🧑‍🎓 普通用户"
    st.info(f"身份: {user_label}\n账号: {st.session_state.username}")

    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.clear();
        st.rerun()

    st.divider()
    st.subheader("📌 功能导航")
    for nav in ["💬 智能对话", "🗄️ 知识库管理"]:
        style = "primary" if st.session_state.current_page == nav else "secondary"
        if st.button(nav, use_container_width=True, type=style):
            st.session_state.current_page = nav;
            st.rerun()

    # 【核心功能：BYOK 允许用户更改默认配置】
    st.divider()
    with st.expander("⚙️ 推理引擎配置 (默认智谱)"):
        cfg = st.session_state.ai_config
        m = st.radio("运行模式", ["云端 API (智谱/DeepSeek)", "本地 Ollama"],
                     index=0 if cfg["mode"] == "cloud" else 1)
        cfg["mode"] = "cloud" if "云端" in m else "local"

        if cfg["mode"] == "cloud":
            cfg["cloud_base"] = st.text_input("API Base", cfg["cloud_base"])
            cfg["cloud_model"] = st.text_input("模型名", cfg["cloud_model"])
            cfg["cloud_key"] = st.text_input("API 密钥", cfg["cloud_key"], type="password")
        else:
            cfg["local_name"] = st.text_input("Ollama 模型名", cfg["local_name"])

        if st.button("💾 保存并应用配置", use_container_width=True):
            save_to_memory();
            ensure_engine_ready()
            st.toast("引擎已重新挂载！", icon="🚀")

    st.divider()
    st.subheader("💬 对话历史")
    if st.button("➕ 开启新对话", use_container_width=True, type="primary"):
        nid = str(uuid.uuid4())
        st.session_state.chats[nid] = {"name": "新会话", "messages": [], "selected_docs": []}
        st.session_state.active_chat, st.session_state.current_page = nid, "💬 智能对话"
        save_to_memory();
        st.rerun()

    for cid, cinfo in list(st.session_state.chats.items()):
        is_active = (cid == active_id)
        btn_label = f"👉 {cinfo['name']}" if is_active else cinfo['name']
        if st.button(btn_label, key=f"nav_{cid}", use_container_width=True):
            st.session_state.active_chat = cid
            st.session_state.current_page = "💬 智能对话"
            save_to_memory();
            st.rerun()

# =================================================================
# 5. 交互细节：公共库弹窗拦截逻辑 (防止误操作)
# =================================================================
pub_state_key = f"pub_state_{active_id}"
sw_widget_key = f"sw_widget_{active_id}"
if pub_state_key not in st.session_state: st.session_state[pub_state_key] = True


@st.dialog("⚠️ 确认操作")
def confirm_disable_dialog():
    st.warning("您当前选中了公共库文件。如果强制关闭关联，这些文件将从检索范围中自动移除。")
    c1, c2 = st.columns(2)
    if c1.button("确认关闭", type="primary", use_container_width=True):
        st.session_state[pub_state_key] = False
        chat_data["selected_docs"] = [d for d in chat_data["selected_docs"] if not d.startswith("🌐")]
        save_to_memory();
        st.rerun()
    if c2.button("取消", use_container_width=True): st.rerun()


def handle_pub_toggle():
    new_val = st.session_state[sw_widget_key]
    if not new_val:
        if any(d.startswith("🌐") for d in chat_data.get("selected_docs", [])):
            confirm_disable_dialog()
        else:
            st.session_state[pub_state_key] = False
    else:
        st.session_state[pub_state_key] = True


st.session_state[sw_widget_key] = st.session_state[pub_state_key]

# =================================================================
# 6. 页面路由与主内容渲染
# =================================================================
page = st.session_state.current_page

# -----------------------------------------------------------------
# A: 智能对话页面 (支持 自动命名/续答/勾选记忆)
# -----------------------------------------------------------------
if page == "💬 智能对话":
    # 确保引擎就绪
    ensure_engine_ready()

    col_scope, col_check = st.columns([3, 1])
    with col_scope:
        sources = st.session_state.agent.get_available_sources(session_id=active_id)
        opts = [f"🌐 {d}" for d in sources["public"]] + [f"🔒 {d}" for d in sources["private"]]
        if not st.session_state[pub_state_key]:
            opts = [d for d in opts if not d.startswith("🌐")]

        # 【核心细节：跨页面选中文档记忆】
        defaults = [d for d in chat_data["selected_docs"] if d in opts]
        sel = st.multiselect("📚 检索范围 (留空则默认全选)", opts, default=defaults)

        if sel != chat_data["selected_docs"]:
            chat_data["selected_docs"] = sel;
            save_to_memory()

    with col_check:
        st.write(" ");
        st.write(" ")
        st.checkbox("🔍 关联公共知识库", value=st.session_state[pub_state_key], key=sw_widget_key,
                    on_change=handle_pub_toggle)

    st.markdown("---")

    # 渲染历史记录
    for msg in chat_data["messages"]:
        avatar = "🧑‍🎓" if msg["role"] == "user" else "🤖"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # 【核心细节：提问中断续答检测】
    last_is_user = len(chat_data["messages"]) > 0 and chat_data["messages"][-1]["role"] == "user"

    bot_area = st.columns([1, 15])
    with bot_area[0]:
        with st.popover("📎"):
            st.write("### 附件上传")
            st.caption("支持 PDF/Word/Excel/TXT，仅存入私有库")
            files = st.file_uploader("选择文件", type=SUPPORTED_FORMATS, accept_multiple_files=True,
                                     key=st.session_state.chat_up_key)
            if files and st.button("解析入库"):
                p = st.progress(0)
                for i, f in enumerate(files):
                    process_and_ingest(f, f"session_{active_id}")
                    p.progress((i + 1) / len(files))
                st.session_state.chat_up_key = str(uuid.uuid4());
                st.toast("私有文档已入库");
                st.rerun()

    with bot_area[1]:
        prompt = st.chat_input("向 CourseRobot 提问...")

        # 续答按钮
        retry = st.button("🔄 检测到回答中断，点击继续") if last_is_user and not prompt else False

        if prompt or retry:
            current_q = chat_data["messages"][-1]["content"] if retry else prompt

            if not retry:
                chat_data["messages"].append({"role": "user", "content": current_q})
                # 【核心细节：AI 自动重命名会话标题】
                if chat_data["name"] == "新会话" and st.session_state.agent.llm:
                    try:
                        res = st.session_state.agent.llm.invoke(f"提取核心主题，10字内，无标点：{current_q}")
                        if res and getattr(res, 'content', None):
                            title = res.content.strip().replace("。", "").replace("《", "").replace("》", "")[:10]
                            if title: chat_data["name"] = title
                    except:
                        pass
                save_to_memory();
                st.rerun()

            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("正在检索并思考..."):
                    try:
                        clean_docs = [d[2:] for d in chat_data["selected_docs"]]
                        ans, cites = st.session_state.agent.ask(current_q, clean_docs, active_id,
                                                                st.session_state[pub_state_key])
                        full_ans = f"{ans}\n\n**📍 知识溯源：**\n" + "\n".join([f"- {c}" for c in cites])
                        st.markdown(full_ans)
                        chat_data["messages"].append({"role": "assistant", "content": full_ans})
                        save_to_memory()
                    except Exception as e:
                        st.error(f"❌ 大模型请求失败！请检查 API 密钥或网络环境。详情: {e}")

# -----------------------------------------------------------------
# B: 知识库管理页面 (精细权限流转)
# -----------------------------------------------------------------
elif page == "🗄️ 知识库管理":
    st.title("🗄️ 资产管理中枢")

    if st.session_state.role == "admin":
        st.success("👑 管理员特权：您可以进行全局公共库的注入与文档流转。")
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📥 公共库批量注入")
            g_files = st.file_uploader("全格式支持 (PDF/Word/Excel/TXT)", type=SUPPORTED_FORMATS,
                                       accept_multiple_files=True, key=st.session_state.glob_up_key)
            if g_files and st.button("一键全局入库", type="primary"):
                p = st.progress(0)
                for i, f in enumerate(g_files):
                    process_and_ingest(f, "public")
                    p.progress((i + 1) / len(g_files))
                st.success("✨ 公共库已更新完毕！")
                st.session_state.glob_up_key = str(uuid.uuid4());
                st.rerun()

        with c2:
            st.subheader("🔁 权限流转控制")
            s_dict = st.session_state.agent.get_available_sources(session_id=active_id)
            l_all = [f"🌐 {d}" for d in s_dict["public"]] + [f"🔒 {d}" for d in s_dict["private"]]
            if l_all:
                target = st.selectbox("选择目标文档", l_all)
                is_pub = target.startswith("🌐")
                raw_name = target[2:]

                if is_pub:
                    dest_chat = st.selectbox("流转至指定会话私有：", options=list(st.session_state.chats.keys()),
                                             format_func=lambda x: st.session_state.chats[x]['name'])
                    if st.button("⬇️ 降级为私有 (空降到选定对话)"):
                        st.session_state.agent.change_file_scope(raw_name, "public", f"session_{dest_chat}");
                        st.rerun()
                elif st.button("⬆️ 提拔为全局公共"):
                    st.session_state.agent.change_file_scope(raw_name, f"session_{active_id}", "public");
                    st.rerun()
            else:
                st.warning("暂无可用文档资产。")
    else:
        st.info("👤 您目前仅可管理当前会话的私有文档资产。")
        sources = st.session_state.agent.get_available_sources(session_id=active_id)
        for d in sources["private"]:
            st.text(f"🔒 {d} (私有权限)")
