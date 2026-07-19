import streamlit as st
import gspread
from google.oauth2 import service_account
from datetime import datetime, date, timedelta
from collections import defaultdict
import json

st.set_page_config(page_title="我的學習小站", page_icon="📚")

# --- 連接 Google Sheets（現在有 3 個分頁）---
@st.cache_resource
def get_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = json.loads(st.secrets["gcp_service_account_json"])
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=scopes
    )
    gc = gspread.authorize(credentials)
    sh = gc.open_by_key(st.secrets["sheet_id"])
    return sh.worksheet("題庫"), sh.worksheet("作答紀錄"), sh.worksheet("重點")

bank_ws, log_ws, point_ws = get_sheets()

# --- 讀資料 ---
questions = bank_ws.get_all_records()
logs = log_ws.get_all_records()
points = point_ws.get_all_records()

# 重點查詢表：(科目, 單元) -> [重點, ...]
points_lookup = defaultdict(list)
for p in points:
    key = (str(p.get("科目", "")).strip(), str(p.get("單元", "")).strip())
    content = str(p.get("重點內容", "")).strip()
    if content:
        points_lookup[key].append(content)

# --- 小工具 ---
def get_options(q):
    opts = [q.get("選項1"), q.get("選項2"), q.get("選項3"), q.get("選項4")]
    return [str(o) for o in opts if str(o).strip() != ""]

def get_correct(q, opts):
    raw = str(q.get("正解", "")).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(opts):
        return opts[int(raw) - 1]
    return None

# --- 萊特納：從作答紀錄算出每題的複習狀態 ---
INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}  # 盒子 -> 幾天後再複習
MAX_BOX = 5

def compute_state(logs, all_qids):
    history = defaultdict(list)
    for r in logs:
        qid = str(r.get("題號", "")).strip()
        result = str(r.get("對錯", "")).strip()
        ts = str(r.get("時間", "")).strip()
        if not (qid and result in ("O", "X")):
            continue
        try:
            when = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        history[qid].append((when, result))

    today = date.today()
    state = {}
    for qid in all_qids:
        events = sorted(history.get(qid, []))
        if not events:  # 從未作答 = 待練習的新題
            state[qid] = {"box": 0, "due": True}
            continue
        box = 1
        for _, result in events:
            box = min(box + 1, MAX_BOX) if result == "O" else 1
        next_date = events[-1][0].date() + timedelta(days=INTERVALS[box])
        state[qid] = {"box": box, "due": next_date <= today}
    return state

# --- 呈現一組題目、批改、寫紀錄、答錯帶重點 ---
def render_quiz(quiz, form_key):
    with st.form(form_key):
        answers = {}
        for i, q in enumerate(quiz):
            answers[i] = st.radio(
                f"{i+1}. {q['題目']}",
                get_options(q),
                index=None,
                key=f"{form_key}_{i}",
            )
        submitted = st.form_submit_button("送出答案")

    if not submitted:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows, results, score = [], [], 0
    for i, q in enumerate(quiz):
        opts = get_options(q)
        correct = get_correct(q, opts)
        chosen = answers[i]
        is_correct = (
            chosen is not None
            and correct is not None
            and str(chosen).strip() == correct.strip()
        )
        if is_correct:
            score += 1
        rows.append([
            now, str(q.get("題號", "")), str(q.get("題目", "")),
            str(chosen), "O" if is_correct else "X",
        ])
        results.append((i, q, correct, chosen, is_correct))

    log_ws.append_rows(rows)

    st.subheader(f"結果：答對 {score} / {len(quiz)} 題")
    for i, q, correct, chosen, is_correct in results:
        if correct is None:
            st.warning(f"{i+1}. 這題的「正解」欄設定有誤，請檢查試算表")
        elif is_correct:
            st.success(f"{i+1}. 答對 ✔")
        else:
            st.error(f"{i+1}. 答錯 ✘　你選：{chosen}　正解：{correct}")
            if str(q.get("解析", "")).strip():
                st.caption(f"解析：{q['解析']}")
            pts = points_lookup.get(
                (str(q.get("科目", "")).strip(), str(q.get("單元", "")).strip()), []
            )
            if pts:
                st.info("📌 這個單元的重點：\n\n" + "\n".join(f"- {p}" for p in pts))

# ============ 介面 ============
st.title("📚 我的學習小站")

if not questions:
    st.warning("題庫還沒有題目，先到 Google 試算表的「題庫」分頁加幾題吧！")
    st.stop()

mode = st.sidebar.radio("模式", ["📝 練習模式", "🔁 複習模式"])

if mode == "📝 練習模式":
    subjects = sorted({str(q["科目"]) for q in questions if str(q.get("科目", "")).strip()})
    subject = st.selectbox("選擇科目", subjects)
    quiz = [q for q in questions if str(q.get("科目", "")) == subject]
    st.caption(f"本次共 {len(quiz)} 題")
    render_quiz(quiz, "practice_form")

else:  # 複習模式
    all_qids = [str(q.get("題號", "")).strip() for q in questions]
    state = compute_state(logs, all_qids)

    def priority(qid):
        s = state[qid]
        if s["box"] == 0:      # 新題排在複習題之後
            return (2, 0)
        return (1, s["box"])   # 已作答且到期：盒子小的（最近答錯）優先

    due_qids = sorted([qid for qid in all_qids if state[qid]["due"]], key=priority)
    wrong_cnt = sum(1 for qid in due_qids if state[qid]["box"] == 1)
    st.caption(f"今天建議複習 {len(due_qids)} 題，其中 {wrong_cnt} 題是最近答錯的")

    if not due_qids:
        st.success("今天沒有到期的複習題 🎉 去「練習模式」挑戰新題吧！")
        st.stop()

    LIMIT = 10
    qmap = {str(q.get("題號", "")).strip(): q for q in questions}
    quiz = [qmap[qid] for qid in due_qids[:LIMIT]]
    if len(due_qids) > LIMIT:
        st.caption(f"（先做前 {LIMIT} 題，其餘下次再複習）")
    render_quiz(quiz, "review_form")
