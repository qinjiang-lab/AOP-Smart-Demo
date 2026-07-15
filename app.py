import streamlit as st
import json
import re
from html import unescape
from openai import OpenAI
from datetime import datetime

# -------------------------- 全局配置（写死） --------------------------
BASE_URL = "https://api.deepseek.com"          # 可替换
MODEL_NAME = "deepseek-v4-flash"              # 写死模型名
# API Key 从 st.secrets 中读取
# 本地测试时可在 .streamlit/secrets.toml 中写入：
# DEEPSEEK_API_KEY = "your-api-key"

# -------------------------- 文件路径 --------------------------
INDEX_FILE = "./Index.txt"
SMART_FILE = "./AOP-Smart.json"

# -------------------------- 预设提示词字典 --------------------------
# 注意：长提示词（Literature Analysis）请自行填入完整的英文 prompt。
# 这里只留占位符，以免代码过长。
PRESETS = {
    "Literature Analysis": 
    """Your task is to convert the input toxicological article into a **structured AOP representation** grounded in the provided AOP knowledge base.

---

# General Principles

Please follow these rules:

1. Only extract biological mechanisms supported by evidence from the paper.
2. Do not invent Key Events (KEs), Key Event Relationships (KERs), or AOP-Wiki IDs.
3. If no suitable AOP-Wiki entity exists, explicitly mark it as **Missing**.
4. Prefer precision over recall.
5. Maintain traceability between extracted knowledge and the original paper.
6. Clearly distinguish:
   - Confirmed evidence
   - Strong mechanistic inference
   - Hypothetical knowledge gaps

The final output should be concise, structured, and suitable for AOP knowledge curation.

---

# Step 1. Key Event (KE) Extraction

Identify all biologically meaningful Key Events described in the article.

Exclude:
- Simple experimental observations without mechanistic meaning.
- General physiological changes without clear biological relevance.

For each Key Event, generate the following table:

| AOP-Wiki KE ID | KE Title | Description | Biological Level | Organ/Tissue | Cell Type | Evidence Type | Evidence from Paper |
|---|---|---|---|---|---|---|

## Requirements:

### AOP-Wiki KE ID
- If an exact matching KE exists in the provided knowledge base:
  - Provide the KE ID, example: KE1576
- If no suitable KE exists:
  - Write: `Missing`

### KE Title
- Use official AOP-Wiki terminology whenever possible.
- If missing, provide a concise biological event name.

### Biological Level
Choose one:

- Molecular
- Cellular
- Tissue
- Organ
- Organism

### Description
- The description field is limited to one sentence.

### Evidence Type

Choose one:

- Direct experimental evidence
- Strong mechanistic inference
- Hypothetical extension

### Evidence from Paper
Provide:
- The most relevant experimental finding.
- A short quote or accurate summary from the article.

---

# Step 2. Key Event Relationship (KER) Extraction

Identify causal relationships between Key Events.

Only include relationships supported by:

- Experimental evidence from the paper, or
- Strong established biological mechanisms.

Do not create KERs only because two events are biologically related;
the relationship must represent a causal transition within an AOP framework.

Generate the following table:

| Upstream KE | Downstream KE | KE IDs | Relationship Description | Evidence Type | Evidence from Paper |
|---|---|---|---|---|---|

## Requirements:

### KE IDs format:

Examples:

KE1115 → KE1392
KE1115 → Missing
Missing → KE344

### Evidence Type:
- Direct experimental evidence
- Strong mechanistic inference
- Hypothetical extension

### Relationship Description

Briefly explain:

- Biological mechanism
- Direction of change
- Why upstream event can lead to downstream event

Do not include unsupported causal assumptions.

---

# Step 3. Candidate AOP Reconstruction

## Candidate AOP Reconstruction and Comparison with Existing AOPs

Generate:

### Candidate AOP

Stressor → MIE → KE1 → KE2 → ... → AO


### Closest Existing AOP-Wiki Pathway

AOP ID:
AOP title:

Stressor → MIE → KE1 → KE2 → ... → AO

### MIE
If the molecular initiating event cannot be identified, explicitly state "Unknown".
Do not infer an MIE solely from downstream events.

### AOP
Only report an existing AOP if the pathway is explicitly available in the provided AOP knowledge base.
Otherwise write: No matching AOP identified.

### Comparison

Explain:
- Shared Key Events
- Different Key Events
- Missing KERs
- Potential extension of existing AOP

---

# Final Output Requirements

The final response must:

- Use Markdown tables.
- Avoid unnecessary long explanations.
- Keep each description concise.
- Preserve evidence traceability.
- Never fabricate:
  - KE IDs
  - KER IDs
  - Existing AOP pathways

Always distinguish:

## Confirmed AOP Knowledge

(Directly supported by experimental evidence)

## Missing Knowledge

(Not represented in current AOP-Wiki but suggested by the paper)

## Hypothetical Extensions

(Mechanistically plausible but requiring further validation)

---

# Input Article

[Insert full paper text here]""",   # <--- 请自行粘贴完整的 "Literature Analysis" 提示词
    "毒性预测": "分析以下文献，预测该化学物质可能触发的AOP通路，并说明从分子起始事件到不良结局的因果链条。",
    "机制总结": "请归纳以下文献中描述的AOP机制，重点说明KE之间的因果关系和生物学合理性。",
}

# -------------------------- KE ID 超链接转换函数 --------------------------
def link_ke_ids(text):
    """将文本中的 KE数字（如 KE1574）替换为指向 AOP-Wiki 的超链接"""
    pattern = r'\b(KE)(\d+)\b'
    def replace(match):
        ke_prefix = match.group(1)   # "KE"
        ke_number = match.group(2)   # "1574"
        url = f"https://aopwiki.org/events/{ke_number}"
        return f'<a href="{url}" target="_blank" style="color:#1f77b4; font-weight:500; text-decoration:none;">{ke_prefix}{ke_number}</a>'
    return re.sub(pattern, replace, text)

# -------------------------- 核心函数（与 Tkinter 版保持一致） --------------------------
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

# 初始化 session_state 预设状态
if "preset_prompt" not in st.session_state:
    st.session_state.preset_prompt = ""
if "preset_name" not in st.session_state:
    st.session_state.preset_name = "None"

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("⚙️ parameter setting")
    
    max_tokens = st.number_input("📝 Max Output Tokens", value=20480, step=256)
    st.caption("Controls AI response length.")
    
    top_n = st.number_input("🎯 Top N KEs", value=10, min_value=1, max_value=500)
    st.caption("How many Key Events to fetch — more context vs. precision.")

    st.markdown("---")
    st.markdown("### 📖 How to use")
    st.markdown("""
    1. **Click** a preset button (e.g., *Literature Analysis*) above the input box.  
    2. **Paste** your article or question into the text area.  
    3. **Press** the *Run* button and wait for the AI to generate the AOP report.
    """)
    st.caption("💡 The preset adds a structured prompt to guide the AI. You can also leave it empty and enter your own question.")
    
    st.markdown("---")
    st.caption("Currently using DeepSeek-V4-Flash (lightweight demo version).")
    st.caption("📧 If you have any related questions, just ping me at niuqinjiang@163.com.")
    st.caption("🚀 For stronger models, check out local deployment: https://github.com/qinjiang-lab/AOP-Smart")
    st.caption("Current Preset Literature Analysis")

# ---------- 主区域：预设按钮 ----------
st.markdown("---")
col_state, col_buttons = st.columns([1, 4])
with col_state:
    st.write(f"**Current Preset:** {st.session_state.preset_name}")

with col_buttons:
    # 根据 PRESETS 数量生成按钮
    num_presets = len(PRESETS)
    cols = st.columns(num_presets + 1)  # +1 给 Clear 按钮
    for idx, (name, prompt) in enumerate(PRESETS.items()):
        with cols[idx]:
            if st.button(name, key=f"preset_{idx}"):
                st.session_state.preset_prompt = prompt
                st.session_state.preset_name = name
                st.rerun()
    with cols[-1]:
        if st.button("Clear Preset", key="clear_preset"):
            st.session_state.preset_prompt = ""
            st.session_state.preset_name = "None"
            st.rerun()
st.markdown("---")

# ---------- 主区域：输入框 ----------
task = st.text_area("📝 Enter your question (Task)", key="task_input", height=150,
                    placeholder="e.g. What are the key events leading to liver fibrosis?")

if st.button("🚀 Run", type="primary"):
    if not task.strip():
        st.warning("Please enter your question")
        st.stop()

    # 拼接预设
    preset = st.session_state.get("preset_prompt", "")
    final_question = preset + "\n\n" + task if preset else task

    # 1. 读取 API Key
    api_key = st.secrets.get("DEEPSEEK_API_KEY")
    if not api_key:
        st.error("❌ API Key not found. Please set DEEPSEEK_API_KEY in secrets.")
        st.stop()

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    temperature = 0.0

    # 2. Step 1: KE 选择（使用原始 task，不包含预设）
    with st.spinner("🧠 Selecting relevant Key Events ..."):
        ke_ids = get_relevant_ke_ids(task, MODEL_NAME, temperature, top_n, client)

    if not ke_ids:
        st.error("❌ No relevant KE was found. Please try another question.")
        st.stop()

    st.success(f"✅ Selected {len(ke_ids)} Key Events: {ke_ids}")

    # 3. Step 2: 构建上下文
    with st.spinner("📚 Building the context..."):
        context_json, stats = build_context_from_ke_ids(ke_ids)

    stat_msg = (
        f"**Activated KE**: {stats['activated_ke_count']} ({stats['ke_percent']}%)  \n"
        f"**Activated KER**: {stats['activated_ker_count']} ({stats['ker_percent']}%)  \n"
        f"**Activated AOP**: {stats['activated_aop_count']} ({stats['aop_percent']}%)  \n"
        f"**Context Token Count (approx.)**: {stats['context_word_count']}"
    )
    st.info(stat_msg)

    # 4. Step 3: 流式推理（使用 final_question）
    with st.chat_message("assistant"):
        # 定义生成器
        def generate_response(question):
            try:
                stream = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are AOP-Smart, an AI assistant for AOP reasoning. Answer based on provided context."},
                        {"role": "user", "content": f"""
<AOP_CONTEXT>
{context_json}
</AOP_CONTEXT>

<Question>
{question}
</Question>
"""}
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

        # 手动收集流式内容，结束后替换 KE ID 为超链接
        placeholder = st.empty()
        full_response = ""

        # 流式输出并实时显示（带光标效果）
        for chunk in generate_response(final_question):
            full_response += chunk
            placeholder.markdown(full_response + "▌")

        # 输出完成后，替换 KE ID 为超链接
        linked_response = link_ke_ids(full_response)
        placeholder.markdown(linked_response, unsafe_allow_html=True)

    # 可选：保存历史（可自行添加）
    # 如想保存，可写入 session_state 或文件
