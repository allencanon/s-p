import streamlit as st
import gspread
import pandas as pd
from google.oauth2 import service_account
from datetime import datetime, date, timedelta
from collections import defaultdict
import json

st.set_page_config(page_title="我的學習小站", page_icon="📚")

# --- 連接 Google Sheets（3 個分頁）---
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

# --- 萊特納：從作答紀錄算出每題狀態 ---
INTERVALS = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30}
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
        if not events:
            state[qid] = {"box": 0, "due": True}
            continue
        box = 1
        for _, result in events:
            box = min(box + 1, MAX_BOX) if result == "O" else 1
        next_date = events[-1][0].date() + timedelta(days=INTERVALS[box])
        state[qid] = {"box": box, "due": next_date <= today}
    return state

# --- 出題、批改、寫紀錄、答錯帶重點 ---
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

# --- 家長儀表板 ---
def render_dashboard():
    st.header("👨‍👩‍👧 家長儀表板")
    if not logs:
        st.info("還沒有任何作答紀錄。")
        return

    qinfo = {}
    for q in questions:
        qid = str(q.get("題號", "")).strip()
        if qid:
            qinfo[qid] = {
                "科目": str(q.get("科目", "")).strip(),
                "單元": str(q.get("單元", "")).strip(),
                "題目": str(q.get("題目", "")).strip(),
            }

    rows = []
    for r in logs:
        qid = str(r.get("題號", "")).strip()
        res = str(r.get("對錯", "")).strip()
        if qid in qinfo and res in ("O", "X"):
            rows.append({
                "題號": qid, "科目": qinfo[qid]["科目"], "單元": qinfo[qid]["單元"],
                "題目": qinfo[qid]["題目"], "對錯": res, "correct": 1 if res == "O" else 0,
            })
    if not rows:
        st.info("紀錄裡還沒有能對應到題庫的作答。")
        return

    df = pd.DataFrame(rows)

    # 總覽
    c1, c2, c3 = st.columns(3)
    c1.metric("總作答次數", len(df))
    c2.metric("整體正確率", f"{df['correct'].mean()*100:.0f}%")
    c3.metric("練習過的題數", df["題號"].nunique())

    # 各科正確率
    st.subheader("各科正確率")
    subj = df.groupby("科目")["correct"].agg(題數="count", 正確率="mean")
    subj["正確率"] = (subj["正確率"] * 100).round(0).astype(int)
    st.bar_chart(subj["正確率"])
    st.dataframe(subj)

    # 最弱單元
    st.subheader("最弱單元（優先加強）")
    unit = (
        df.groupby(["科目", "單元"])["correct"]
        .agg(題數="count", 正確率="mean")
        .reset_index()
    )
    unit = unit[unit["題數"] >= 3].copy()
    if len(unit):
        unit["正確率"] = (unit["正確率"] * 100).round(0).astype(int)
        unit = unit.sort_values("正確率")
        st.dataframe(unit, hide_index=True)
    else:
        st.caption("每個單元累積作答滿 3 次後才會列入，多練幾題就會出現。")

    # 反覆答錯的題目
    st.subheader("反覆答錯、還沒攻克的題目")
    state = compute_state(logs, list(qinfo.keys()))
    wrong = (
        df[df["對錯"] == "X"]
        .groupby(["題號", "科目", "單元", "題目"])
        .size().reset_index(name="答錯次數")
    )
    wrong["目前盒子"] = wrong["題號"].map(lambda x: state.get(x, {}).get("box", 0))
    stuck = wrong[wrong["目前盒子"] == 1].sort_values("答錯次數", ascending=False)
    if len(stuck):
        st.dataframe(stuck[["題號", "科目", "單元", "題目", "答錯次數"]], hide_index=True)
        st.caption("這些題最近一次仍答錯，建議陪孩子一起看。")
    else:
        st.success("目前沒有反覆卡關的題目 🎉")

# ============ 介面 ============
st.title("📚 我的學習小站")

if not questions:
    st.warning("題庫還沒有題目，先到 Google 試算表的「題庫」分頁加幾題吧！")
    st.stop()

mode = st.sidebar.radio("模式", ["📝 練習模式", "🔁 複習模式", "👨‍👩‍👧 家長儀表板"])

if mode == "📝 練習模式":
    subjects = sorted({str(q["科目"]) for q in questions if str(q.get("科目", "")).strip()})
    subject = st.selectbox("選擇科目", subjects)
    quiz = [q for q in questions if str(q.get("科目", "")) == subject]
    st.caption(f"本次共 {len(quiz)} 題")
    render_quiz(quiz, "practice_form")

elif mode == "🔁 複習模式":
    all_qids = [str(q.get("題號", "")).strip() for q in questions]
    state = compute_state(logs, all_qids)

    def priority(qid):
        s = state[qid]
        if s["box"] == 0:
            return (2, 0)
        return (1, s["box"])

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

else:  # 家長儀表板（需要密碼）
    if not st.session_state.get("parent_ok"):
        pw = st.text_input("請輸入家長密碼", type="password")
        if pw and pw == st.secrets.get("parent_password", ""):
            st.session_state["parent_ok"] = True
        elif pw:
            st.error("密碼錯誤")
    if st.session_state.get("parent_ok"):
        render_dashboard()
    else:
        st.stop()
