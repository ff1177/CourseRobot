# =================================================================
# ⚠️ 核心兼容性补丁：必须在所有 import 之前执行
# 解决 ChromaDB 在 Streamlit Cloud (Linux) 环境下 SQLite 版本过低的问题
# =================================================================
import sys
import os

# 检查运行环境，非 Windows 系统强制使用 pysqlite3
if os.name != 'nt':
    try:
        import pysqlite3

        sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
    except ImportError:
        pass

import streamlit as st
import uuid
import json
import time
import shutil
import re
import urllib.parse
from chat_agent import DFR_RAG_Agent
from processor_utils import process_and_ingest

# --- 基础配置 ---
st.set_page_config(
    page_title="CourseRobot 智能中枢",
    layout="wide",
    page_icon="🎓",
    initial_sidebar_state="expanded"
)
SUPPORTED_FORMATS = ["pdf", "docx", "txt", "xlsx", "csv"]

# ==========================================
# 1. 登录系统 (RBAC 鉴权)
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    _, col_login, _ = st.columns([1, 1.5, 1])
    with col_login:
        st.write("");
        st.write("")
        st.title("🎓 CourseRobot 登录")
        st.info("💡 演示账号：admin/admin | user/123456")
        with st.form("login_gate"):
            u = st.text_input("用户名")
            p = st.text_input("密码", type="password")
            if st.form_submit_button("进入智能中枢", type="primary", use_container_width=True):
                if (u == "admin" and p == "admin") or (u == "user" and p == "123456"):
                    st.session_state.logged_in, st.session_state.username = True, u
                    st.session_state.role = "admin" if u == "admin" else "user"
                    st.rerun()
                else:
                    st.error("❌ 凭证错误")
    st.stop()


# ==========================================
# 2. 持久化存储记忆逻辑
# ==========================================
def get_memory_file():
    return f"course_robot_sessions_{st.session_state.username}.json"


def save_to_memory():
    data = {
        "chats": st.session_state.chats,
        "active_chat": st.session_state.active_chat,
        "ai_config": st.session_state.ai_config
    }
    with open(get_memory_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_from_memory():
    if os.path.exists(get_memory_file()):
        try:
            with open(get_memory_file(), "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}


# ==========================================
# 3. 初始化全局状态与引擎挂载
# ==========================================
if "agent" not in st.session_state:
    st.session_state.agent = DFR_RAG_Agent()


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
    # 默认挂载智谱配置
    st.session_state.ai_config = mem_data.get("ai_config", {
        "mode": "cloud",
        "cloud_model": "glm-4",
        "cloud_base": "https://open.bigmodel.cn/api/paas/v4/",
        "cloud_key": "",
        "local_name": "qwen2"
    })

    if "chats" in mem_data and "active_chat" in mem_data:
        st.session_state.chats, st.session_state.active_chat = mem_data["chats"], mem_data["active_chat"]
    else:
        init_id = str(uuid.uuid4())
        st.session_state.chats = {init_id: {"name": "新会话", "messages": [], "selected_docs": []}}
        st.session_state.active_chat = init_id
        save_to_memory()
    ensure_engine_ready()

if "current_page" not in st.session_state: st.session_state.current_page = "💬 智能对话"
if "chat_up_key" not in st.session_state: st.session_state.chat_up_key = str(uuid.uuid4())
if "glob_up_key" not in st.session_state: st.session_state.glob_up_key = str(uuid.uuid4())

active_id = st.session_state.active_chat
chat_data = st.session_state.chats[active_id]


# ==========================================
# 🗑️ 辅助函数：物理清理本地文件资产
# ==========================================
def wipe_physical_files(filename):
    """彻底抹除硬盘上的 md 文件和图片文件夹"""
    # 1. 删 MD 文件
    md_path = os.path.join("data_source", filename)
    if os.path.exists(md_path):
        os.remove(md_path)
    # 2. 删 图表文件夹
    stem = os.path.splitext(filename)[0]
    asset_dir = os.path.join("extracted_assets", stem)
    if os.path.exists(asset_dir):
        shutil.rmtree(asset_dir)


# ==========================================
# 🖼️ 核心功能：大模型回复内容多模态渲染器
# ==========================================
def render_message_with_images(text):
    """拦截 Markdown 图片语法，使用原生 st.image 渲染"""
    # 按 Markdown 图片语法分割文本
    parts = re.split(r'(!\[.*?\]\(.*?\))', text)
    for part in parts:
        if part.startswith('![') and '](' in part:
            match = re.search(r'\((.*?)\)', part)
            if match:
                raw_path = match.group(1)
                img_path = urllib.parse.unquote(raw_path)  # URL 解码还原中文路径
                if os.path.exists(img_path):
                    st.image(img_path, caption="📊 相关知识库图表展示")
                else:
                    st.caption(f"*(⚠️ 图表资产文件可能已丢失: {img_path})*")
        elif part.strip():
            st.markdown(part)


# ==========================================
# 4. 侧边栏交互 (BYOK & 对话管理)
# ==========================================
with st.sidebar:
    st.title("🤖 CourseRobot")
    st.info(
        f"身份: {'👑 管理员' if st.session_state.role == 'admin' else '🧑‍🎓 用户'}\n账号: {st.session_state.username}")
    if st.button("🚪 退出登录", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    st.divider()
    for nav in ["💬 智能对话", "🗄️ 知识库管理"]:
        if st.button(nav, use_container_width=True,
                     type="primary" if st.session_state.current_page == nav else "secondary"):
            st.session_state.current_page = nav
            st.rerun()

    st.divider()
    with st.expander("⚙️ 推理引擎配置 (BYOK)"):
        cfg = st.session_state.ai_config
        m = st.radio("运行模式", ["云端 API (智谱)", "本地 Ollama"], index=0 if cfg["mode"] == "cloud" else 1)
        cfg["mode"] = "cloud" if "云端" in m else "local"

        if cfg["mode"] == "cloud":
            cfg["cloud_base"] = st.text_input("API Base", cfg["cloud_base"])
            cfg["cloud_model"] = st.text_input("模型名", cfg["cloud_model"])
            cfg["cloud_key"] = st.text_input("API 密钥", cfg["cloud_key"], type="password")
        else:
            cfg["local_name"] = st.text_input("Ollama 模型名", cfg["local_name"])

        if st.button("💾 应用配置", use_container_width=True):
            save_to_memory()
            ensure_engine_ready()
            st.toast("引擎已重载！")

    st.divider()
    st.subheader("💬 对话历史")
    if st.button("➕ 开启新对话", use_container_width=True, type="primary"):
        nid = str(uuid.uuid4())
        st.session_state.chats[nid] = {"name": "新会话", "messages": [], "selected_docs": []}
        st.session_state.active_chat = nid
        st.session_state.current_page = "💬 智能对话"
        save_to_memory()
        st.rerun()

    # 🗑️ 会话列表及级联删除按钮
    for cid, cinfo in list(st.session_state.chats.items()):
        is_active = (cid == active_id)
        col_btn, col_del = st.columns([5, 1])
        with col_btn:
            if st.button(f"👉 {cinfo['name']}" if is_active else cinfo['name'], key=f"nav_{cid}",
                         use_container_width=True):
                st.session_state.active_chat = cid
                st.session_state.current_page = "💬 智能对话"
                save_to_memory()
                st.rerun()
        with col_del:
            if st.button("🗑️", key=f"del_{cid}", help="彻底删除此对话及其私有知识"):
                # 1. 深度销毁该会话专属的私有向量数据
                st.session_state.agent.delete_session_data(cid)
                # 2. 从状态机中移除
                del st.session_state.chats[cid]
                # 3. 如果删光了，自动补一个新对话
                if not st.session_state.chats:
                    nid = str(uuid.uuid4())
                    st.session_state.chats[nid] = {"name": "新会话", "messages": [], "selected_docs": []}
                    st.session_state.active_chat = nid
                elif active_id == cid:  # 如果删的是当前正在看的，切到下一个
                    st.session_state.active_chat = list(st.session_state.chats.keys())[0]
                save_to_memory()
                st.rerun()

# ==========================================
# 5. 防误触拦截：公共库关联开关
# ==========================================
pub_state_key = f"pub_state_{active_id}"
sw_widget_key = f"sw_widget_{active_id}"
if pub_state_key not in st.session_state:
    st.session_state[pub_state_key] = True


@st.dialog("⚠️ 确认操作")
def confirm_disable_dialog():
    st.warning("您当前选中了公共库文件。如果强制关闭关联，这些文件将从检索范围中自动移除。")
    if st.button("确认关闭", type="primary", use_container_width=True):
        st.session_state[pub_state_key] = False
        chat_data["selected_docs"] = [d for d in chat_data.get("selected_docs", []) if not d.startswith("🌐")]
        save_to_memory()
        st.rerun()


def handle_pub_toggle():
    if not st.session_state[sw_widget_key]:
        if any(d.startswith("🌐") for d in chat_data.get("selected_docs", [])):
            confirm_disable_dialog()
        else:
            st.session_state[pub_state_key] = False
    else:
        st.session_state[pub_state_key] = True


st.session_state[sw_widget_key] = st.session_state[pub_state_key]

# ==========================================
# 6. 主页面渲染路由
# ==========================================
page = st.session_state.current_page

if page == "💬 智能对话":
    ensure_engine_ready()

    # --- 顶栏：多选库控制 ---
    col_scope, col_check = st.columns([3, 1])
    with col_scope:
        sources = st.session_state.agent.get_available_sources(session_id=active_id)
        opts = [f"🌐 {d}" for d in sources["public"]] + [f"🔒 {d}" for d in sources["private"]]
        if not st.session_state[pub_state_key]:
            opts = [d for d in opts if not d.startswith("🌐")]

        defaults = [d for d in chat_data.get("selected_docs", []) if d in opts]
        sel = st.multiselect("📚 检索范围 (留空则默认全选)", opts, default=defaults)
        if sel != chat_data.get("selected_docs", []):
            chat_data["selected_docs"] = sel
            save_to_memory()

    with col_check:
        st.write(" ");
        st.write(" ")
        st.checkbox("🔍 关联公共知识库", value=st.session_state[pub_state_key], key=sw_widget_key,
                    on_change=handle_pub_toggle)

    st.markdown("---")

    # --- 渲染消息历史 ---
    for msg in chat_data["messages"]:
        with st.chat_message(msg["role"], avatar="🧑‍🎓" if msg["role"] == "user" else "🤖"):
            # 💡 核心修改：使用多模态渲染器替代纯文本 markdown
            render_message_with_images(msg["content"])

    last_is_user = len(chat_data["messages"]) > 0 and chat_data["messages"][-1]["role"] == "user"

    # --- 底部控制台：上传与聊天 ---
    bot_area = st.columns([1, 15])
    with bot_area[0]:
        with st.popover("📎"):
            files = st.file_uploader("传附件", type=SUPPORTED_FORMATS, accept_multiple_files=True,
                                     key=st.session_state.chat_up_key)
            if files and st.button("解析入库"):
                p = st.progress(0)
                for i, f in enumerate(files):
                    process_and_ingest(f, f"session_{active_id}")
                    p.progress((i + 1) / len(files))
                st.session_state.chat_up_key = str(uuid.uuid4())
                st.toast("私有文档已入库")
                st.rerun()

    with bot_area[1]:
        prompt = st.chat_input("向 CourseRobot 提问...")
        retry = st.button("🔄 检测到回答中断，点击继续") if last_is_user and not prompt else False

        if prompt or retry:
            current_q = chat_data["messages"][-1]["content"] if retry else prompt

            if not retry:
                chat_data["messages"].append({"role": "user", "content": current_q})
                # AI 自动重命名会话
                if chat_data["name"] == "新会话" and st.session_state.agent.llm:
                    try:
                        res = st.session_state.agent.llm.invoke(f"提取核心主题，10字内，无标点：{current_q}")
                        if res and getattr(res, 'content', None):
                            title = res.content.strip().replace("。", "").replace("《", "").replace("》", "")[:10]
                            if title: chat_data["name"] = title
                    except:
                        pass
                save_to_memory()
                st.rerun()

            # 生成回答
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("正在检索并思考..."):
                    try:
                        clean_docs = [d[2:] for d in chat_data.get("selected_docs", [])]
                        ans, cites = st.session_state.agent.ask(current_q, clean_docs, active_id,
                                                                st.session_state[pub_state_key])
                        full_ans = f"{ans}\n\n**📍 知识溯源：**\n" + "\n".join([f"- {c}" for c in cites])

                        # 💡 核心修改：生成完毕后，也使用多模态渲染器动态展示图片
                        render_message_with_images(full_ans)

                        chat_data["messages"].append({"role": "assistant", "content": full_ans})
                        save_to_memory()
                    except Exception as e:
                        st.error(f"❌ 大模型请求失败！详情: {e}")

elif page == "🗄️ 知识库管理":
    st.title("🗄️ 资产管理中枢")
    s_dict = st.session_state.agent.get_available_sources(session_id=active_id)
    l_all = [f"🌐 {d}" for d in s_dict["public"]] + [f"🔒 {d}" for d in s_dict["private"]]

    # --- 管理员与普通用户视图隔离 ---
    if st.session_state.role == "admin":
        st.success("👑 管理员特权：您可以进行全局公共库的注入与文档流转。")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            st.subheader("📥 批量注入")
            g_files = st.file_uploader("全格式支持", type=SUPPORTED_FORMATS, accept_multiple_files=True,
                                       key=st.session_state.glob_up_key)
            if g_files and st.button("全局入库", type="primary"):
                p = st.progress(0)
                for i, f in enumerate(g_files):
                    process_and_ingest(f, "public")
                    p.progress((i + 1) / len(g_files))
                st.session_state.glob_up_key = str(uuid.uuid4())
                st.rerun()
        with c2:
            st.subheader("🔁 权限流转")
            if l_all:
                target = st.selectbox("选择目标文档", l_all, key="trans_select")
                if target.startswith("🌐"):
                    dest_chat = st.selectbox("流转至指定会话：", options=list(st.session_state.chats.keys()),
                                             format_func=lambda x: st.session_state.chats[x]['name'])
                    if st.button("⬇️ 降级为私有"):
                        st.session_state.agent.change_file_scope(target[2:], "public", f"session_{dest_chat}")
                        st.rerun()
                elif st.button("⬆️ 提拔为全局公共"):
                    st.session_state.agent.change_file_scope(target[2:], f"session_{active_id}", "public")
                    st.rerun()
    else:
        st.info("👤 普通用户视图：您仅可管理当前会话的私有文档资产。")
        for d in s_dict["private"]:
            st.text(f"🔒 {d} (私有权限)")
        c3 = st.container()  # 占位

    # --- 🗑️ 危险操作区：彻底删除文档 ---
    del_options = l_all if st.session_state.role == "admin" else [f"🔒 {d}" for d in s_dict["private"]]

    st.divider()
    st.subheader("🗑️ 危险操作区：文档彻底销毁")
    if del_options:
        col_del_1, col_del_2 = st.columns([3, 1])
        with col_del_1:
            del_target = st.selectbox("选择要彻底粉碎的文档", del_options, key="del_select")
        with col_del_2:
            st.write(" ");
            st.write(" ")
            if st.button("💥 彻底销毁文档", type="primary"):
                is_pub = del_target.startswith("🌐")
                raw_name = del_target[2:]
                scope_val = "public" if is_pub else f"session_{active_id}"

                # 1. 深度清理向量数据库
                st.session_state.agent.delete_document(raw_name, scope_val)
                # 2. 擦除本地物理 Markdown 和 截图碎片
                wipe_physical_files(raw_name)
                # 3. 将已删除的文件从用户的勾选记忆中移除
                if del_target in chat_data.get("selected_docs", []):
                    chat_data["selected_docs"].remove(del_target)

                st.toast(f"已彻底销毁 {raw_name}！", icon="💥")
                save_to_memory()
                time.sleep(0.5)
                st.rerun()
    else:
        st.warning("当前没有可销毁的文档。")