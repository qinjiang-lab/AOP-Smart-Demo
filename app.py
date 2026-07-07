import streamlit as st
import json
import re
from html import unescape
from openai import OpenAI
from datetime import datetime

# -------------------------- 全局配置（写死） --------------------------
BASE_URL = "https://api.deepseek.com"  # 写死，可替换
MODEL_NAME = "deepseek-v4-flash"  # 写死模型名
# API Key 从 st.secrets 中读取，部署时在 Streamlit Cloud 的 Secrets 中设置
# 本地测试时可在 .streamlit/secrets.toml 中写入：
# DEEPSEEK_API_KEY = "your-api-key"

# -------------------------- 文件路径 --------------------------
INDEX_FILE = "./Index.txt"
SMART_FILE = "./AOP-Smart.json"


# -------------------------- 核心函数（基本原封不动） --------------------------
def clean_text(text, max_len, max_sentences=2):
    if not text:
        return "-"
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\b[0-9A-Fa-f]{10,}\b", "", text)
    text = " ".join(text.split())
    sentences = re.split(r'(?<=[.!?]) +', text)
    text = " ".join(sentences[:max_sentences])
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text


clean_text_ke = 200
clean_text_ker = 120
clean_text_ao = 250


def simplify_context(selected_ke, selected_ker, selected_aop, kers, key_events):
    ke_entries = []
    for ke_id, ke in selected_ke.items():
        title = ke.get("title", "") or "-"
        level = ke.get("level", "") or "-"
        organ = ke.get("organ", "") or "-"
        cell = ke.get("cell", "") or "-"
        description = clean_text(ke.get("description", ""), clean_text_ke) or "-"
        applicability = ke.get("applicability", {})
        sex_list = [s.get("sex", "-") or "-" for s in applicability.get("sex", [])]
        life_stage_list = [l.get("life_stage", "-") or "-" for l in applicability.get("life_stage", [])]
        taxonomy_list = [t.get("taxonomy", "-") or "-" for t in applicability.get("taxonomy", [])]
        sex_str = ",".join(sex_list) if sex_list else "-"
        life_stage_str = ",".join(life_stage_list) if life_stage_list else "-"
        taxonomy_str = ",".join(taxonomy_list) if taxonomy_list else "-"
        app_str = f"sex:{sex_str}|life_stage:{life_stage_str}|taxonomy:{taxonomy_str}"
        ke_entry = f"[{ke_id}|{title}|{level}|{organ}|{cell}|{description}|{app_str}]"
        ke_entries.append(ke_entry)

    ke_prompt = """Below is a list of Key Events (KE) in a simplified format.
Each KE is enclosed in square brackets [] with fields separated by '|':
[id | title | level | organ | cell | description | applicability]
- id: Unique identifier of the KE (always present)
- title: Name of the KE (always present)
- level: Biological level (Molecular, Cellular, Tissue, Individual, etc.; use '-' if unknown)
- organ: Target organ or tissue (use '-' if unknown)
- cell: Cell type if applicable (use '-' if unknown)
- description: Short description of the KE (use '-' if empty)
- applicability: Information about sex, life stage, taxonomy in the format
  sex:<list> | life_stage:<list> | taxonomy:<list>
  Use '-' for each category if no information is available.\n"""
    ke_text = "\n KE:\n" + "\n".join(ke_entries) + "\n"

    ker_entries = []
    for ker_id, ker in selected_ker.items():
        upstream = ker.get("upstream_id") or "-"
        downstream = ker.get("downstream_id") or "-"
        description = clean_text(ker.get("description", ""), clean_text_ker) or "-"
        applicability = ker.get("applicability", {})
        sex_list = [s.get("sex") for s in applicability.get("sex", [])] or ["-"]
        life_stage_list = [l.get("life_stage") for l in applicability.get("life_stage", [])] or ["-"]
        taxonomy_list = [t.get("taxonomy") for t in applicability.get("taxonomy", [])] or ["-"]
        app_str = f"sex:{','.join(sex_list)}|life_stage:{','.join(life_stage_list)}|taxonomy:{','.join(taxonomy_list)}"
        ker_entry = f"[{upstream}->{downstream}|{description}|{app_str}]"
        ker_entries.append(ker_entry)
    ker_prompt = """Below is a list of Key Event Relationships (KERs) in a simplified format.
Each KER is in its own square brackets [] in the following format:
[upstream_id -> downstream_id | description | applicability]
- upstream_id: KE ID of the upstream event 
- downstream_id: KE ID of the downstream event
- description: short text describing the causal link (use '-' if none)
- applicability: information about sex, life stage, and taxonomy in the format
  sex:<list> | life_stage:<list> | taxonomy:<list> (use '-' if none)
"""
    ker_text = "\nKER:\n" + "\n".join(ker_entries)

    aop_entries = []
    for aop_id, aop in selected_aop.items():
        title = aop.get("title", "") or "-"
        abstract = clean_text(aop.get("abstract", ""), clean_text_ao) or "-"
        applicability = aop.get("applicability", {})
        sex_list = [s.get("sex", "-") for s in applicability.get("sex", [])] or ["-"]
        life_stage_list = [l.get("life_stage", "-") for l in applicability.get("life_stage", [])] or ["-"]
        taxonomy_list = [t.get("taxonomy", "-") for t in applicability.get("taxonomy", [])] or ["-"]
        app_str = f"sex:{','.join(sex_list)}|life_stage:{','.join(life_stage_list)}|taxonomy:{','.join(taxonomy_list)}"

        def format_ke_list(ids):
            formatted = []
            for ke_id in ids:
                ke_id_str = str(ke_id)
                if ke_id_str in key_events:
                    title = key_events[ke_id_str].get("title", "")
                    formatted.append(f"{ke_id_str}({title})")
                else:
                    formatted.append(ke_id_str)
            return formatted

        mie_ids = format_ke_list([m.get("key_event_id", "-") for m in aop.get("MIEs", [])] or ["-"])
        ke_ids = format_ke_list(aop.get("KEs", []) or ["-"])
        ao_ids = format_ke_list([a.get("key_event_id", "-") for a in aop.get("AOs", [])] or ["-"])

        ker_rels = []
        for kr in aop.get("KE_relationships", []):
            upstream = kers[kr["id"]].get("upstream_id", "-") or "-"
            downstream = kers[kr["id"]].get("downstream_id", "-") or "-"
            ker_rels.append(f"{upstream}->{downstream}")
        if not ker_rels:
            ker_rels = ["-"]

        aop_entry = f"[{aop_id}|{title}|{abstract}|MIEs:{','.join(mie_ids)}|KEs:{','.join(ke_ids)}|AOs:{','.join(ao_ids)}|KERs:{','.join(ker_rels)}|{app_str}]"
        aop_entries.append(aop_entry)

    aop_prompt = """
Below is a list of Adverse Outcome Pathways (AOPs) in simplified format.
Each AOP is represented in square brackets [] with fields separated by '|':
[id | title | abstract | MIEs | KEs | AOs | KERs | applicability]
Definitions:
- MIEs (Molecular Initiating Events): the starting KEs in the pathway (no upstream)
- KEs: intermediate Key Events between MIEs and AOs
- AOs (Adverse Outcomes): the ending KEs in the pathway (no downstream)
- KERs: causal relationships in the format upstream_ke_id -> downstream_ke_id
- applicability: biological applicability information:
    • sex:<list> | life_stage:<list> | taxonomy:<list>
    • '-' means not specified
    """
    aop_text = "AOP:\n" + "\n".join(aop_entries) + "\n"
    overall_prompt = """The following is an AOP knowledge base:\n
    """
    AOP_smart = overall_prompt + "<KE>\n" + ke_prompt + ke_text + "</KE>\n\n" + "<KE_relation>\n" + ker_prompt + ker_text + "\n<KE_relation>" + "\n\n<AOP>\n" + aop_prompt + aop_text + "</AOP>"
    return AOP_smart


def build_context_from_ke_ids(ke_ids):
    with open(SMART_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    key_events = data.get("key_events", {})
    kers = data.get("kers", {})
    aops = data.get("aops", {})

    selected_ke = {}
    selected_ker = {}
    selected_aop = {}

    initial_ke = set(ke_ids)

    downstream_ke = set()
    for ker_id, ker in kers.items():
        upstream = ker.get("upstream_id")
        downstream = ker.get("downstream_id")
        if upstream in initial_ke:
            downstream_ke.add(downstream)
    ke_up = set()
    for ker_id, ker in kers.items():
        up = ker.get("upstream_id")
        down = ker.get("downstream_id")
        if down in initial_ke:
            ke_up.add(up)

    expanded_ke = initial_ke.union(downstream_ke)
    expanded_ke = expanded_ke.union(ke_up)

    for aop_id, aop in aops.items():
        check = 0
        for mie in aop.get("MIEs", []):
            if mie.get("key_event_id") in expanded_ke:
                check = check + 1
        for ke in aop.get("KEs", []):
            if ke in expanded_ke:
                check = check + 1
        for ao in aop.get("AOs", []):
            if ao.get("key_event_id") in expanded_ke:
                check = check + 1
        if check >= 2:
            selected_aop[aop_id] = aop

    for ke_id in expanded_ke:
        if ke_id in key_events:
            selected_ke[ke_id] = key_events[ke_id]

    for ker_id, ker in kers.items():
        upstream = ker.get("upstream_id")
        downstream = ker.get("downstream_id")
        if upstream in expanded_ke and downstream in expanded_ke:
            selected_ker[ker_id] = ker

    context = simplify_context(selected_ke, selected_ker, selected_aop, kers, key_events)

    total_ke_count = len(key_events)
    total_ker_count = len(kers)
    total_aop_count = len(aops)

    activated_ke_count = len(selected_ke)
    activated_ker_count = len(selected_ker)
    activated_aop_count = len(selected_aop)

    ke_percent = activated_ke_count / total_ke_count * 100 if total_ke_count else 0
    ker_percent = activated_ker_count / total_ker_count * 100 if total_ker_count else 0
    aop_percent = activated_aop_count / total_aop_count * 100 if total_aop_count else 0

    context_str = json.dumps(context, ensure_ascii=False)
    word_count = len(re.findall(r'\w+', context_str))

    stats = {
        "activated_ke_count": activated_ke_count,
        "activated_ker_count": activated_ker_count,
        "activated_aop_count": activated_aop_count,
        "ke_percent": round(ke_percent, 2),
        "ker_percent": round(ker_percent, 2),
        "aop_percent": round(aop_percent, 2),
        "context_word_count": word_count
    }

    return json.dumps(context, ensure_ascii=False, indent=2), stats


# -------------------------- Step 1: KE 选择（去除Tkinter依赖） --------------------------
def get_relevant_ke_ids(question, model_name, temperature, top_n, client):
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_data = f.read()

    system_prompt = f"""You are AOP-Smart, an expert system for Adverse Outcome Pathways (AOP).
Below is the index of all known Key Events (KEs).
Each line is in the format:
<KE>
id|title
id|title
id|title
...
</KE>

Task:
Given a user question, select the most relevant KE ids.
Procedure:
Stage 1 — Candidate Filtering:
1. Read all KEs and identify a broad set of potentially relevant candidates.
2. Use high recall: include any KE that is possibly related (semantic, biological, or toxicological relevance).
3. Limit this candidate set to at most 3 × {top_n} KEs.

Stage 2 — Relevance Scoring and Ranking:
4. For each candidate KE, assign a relevance score from 0 to 1:
   - 0 = completely irrelevant
   - 1 = highly relevant
5. Scoring must be based strictly on semantic and biological relevance to the question.
6. Prefer:
   - exact biological processes
   - matching pathways or mechanisms
   - specific toxicological endpoints
7. Penalize:
   - vague or generic KEs
   - weak or indirect associations

Final Selection:
8. Rank all candidate KEs by score (descending).
9. Select the top {top_n} KE ids.

Output:
Return ONLY the KE ids as a ranked list (highest relevance first), in this format:
[1,3,4,5]

Constraints:
- Do NOT output scores
- Do NOT output explanations
- Be deterministic and consistent
- If scores are similar, prefer more specific KE titles
"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{index_data}\n\nQuestion:\n{question}"}
            ],
            temperature=temperature,
            max_tokens=5000
        )
        text = response.choices[0].message.content.strip()
        match = re.search(r"\[(.*?)\]", text)
        if match:
            ids = match.group(1).split(",")
            return [i.strip() for i in ids if i.strip()]
        return []
    except Exception as e:
        st.error(f"KE Selection Error: {e}")
        return []


# -------------------------- Streamlit 界面 --------------------------
st.set_page_config(page_title="AOP-Smart", layout="wide")
st.title("🧪 AOP-Smart")

# ---------- 侧边栏：可调参数 ----------
with st.sidebar:
    st.header("⚙️ parameter setting")
    
    max_tokens = st.number_input("📝 Max Output Tokens", value=4096, step=256)
    st.caption("Controls AI response length.")
    
    top_n = st.number_input("🎯 Top N KEs", value=5, min_value=1, max_value=20)
    st.caption("How many Key Events to fetch — more context vs. precision.")
    
    st.markdown("---")
    st.caption("Currently using DeepSeek-V4-Flash (lightweight demo version).")
    st.caption("💡 This is a cost-efficient variant — results may not fully reflect premium models.")
    st.caption("💰 We've topped up the demo budget — so feel free to explore!")
    st.caption("📧 If the balance somehow runs low, just ping me at niuqinjiang@163.com.")
    st.caption("🚀 For stronger models, check out local deployment: https://github.com/qinjiang-lab/AOP-Smart")
# ---------- 主区域 ----------
task = st.text_area("📝 Enter your question（Task）", height=150, placeholder="for example ：What are the key events leading to liver fibrosis?")

if st.button("🚀 Run", type="primary"):
    if not task.strip():
        st.warning("Please enter your question")
        st.stop()

    # 1. 读取 API Key（从 secrets）
    api_key = st.secrets.get("DEEPSEEK_API_KEY")
    if not api_key:
        st.error("❌ API Key not found")
        st.stop()

    # 2. 初始化 OpenAI 客户端
    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    temperature = 0.0
    # 3. Step 1: 选择 KE（显示进度）
    with st.spinner("🧠 Selecting relevant Key Events ..."):
        ke_ids = get_relevant_ke_ids(task, MODEL_NAME, temperature, top_n, client)

    if not ke_ids:
        st.error("❌ No relevant KE was found. Please try another question.")
        st.stop()

    st.success(f"✅ Select {len(ke_ids)}   Key Events: {ke_ids}")

    # 4. Step 2: 构建上下文（显示统计信息）
    with st.spinner("📚 Building the context..."):
        context_json, stats = build_context_from_ke_ids(ke_ids)

    # 显示统计信息
    stat_msg = (
        f"**Activated KE**: {stats['activated_ke_count']} ({stats['ke_percent']}%)  \n"
        f"**Activated KER**: {stats['activated_ker_count']} ({stats['ker_percent']}%)  \n"
        f"**Activated AOP**: {stats['activated_aop_count']} ({stats['aop_percent']}%)  \n"
        f"**Context Token Count (approx.)**: {stats['context_word_count']}"
    )

    # 5. Step 3: 流式推理
    with st.chat_message("assistant"):
        # 定义生成器
        def generate_response():
            try:
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system",
                         "content": "You are AOP-Smart, an AI assistant for AOP reasoning. Answer based on provided context."},
                        {"role": "user", "content": f"""
<AOP_CONTEXT>
{context_json}
</AOP_CONTEXT>

<Question>
{task}
</Question>
"""
                         }
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            except Exception as e:
                yield f"\n\n❌ Error: {e}"


        # 使用 st.write_stream 实现流式输出
        st.write_stream(generate_response())

    # 可选：保存历史（不强制）
    # 你可以选择将对话记录到 st.session_state 或外部存储
