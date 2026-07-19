import streamlit as st
import gspread
from google.oauth2 import service_account
from datetime import datetime
import json

st.set_page_config(page_title="我的學習小站", page_icon="📚")

# --- 連接 Google Sheets ---
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
    return sh.worksheet("題庫"), sh.worksheet("作答紀錄")

bank_ws, log_ws = get_sheets()

st.title("📚 我的學習小站")

# --- 讀題庫 ---
questions = bank_ws.get_all_records()
if not questions:
    st.warning("題庫還沒有題目，先到 Google 試算表的「題庫」分頁加幾題吧！")
    st.stop()

def get_options(q):
    opts = [q.get("選項1"), q.get("選項2"), q.get("選項3"), q.get("選項4")]
    return [str(o) for o in opts if str(o).strip() != ""]

def get_correct(q, opts):
    raw = str(q.get("正解", "")).strip()
    if raw.isdigit() and 1 <= int(raw) <= len(opts):
        return opts[int(raw) - 1]
    return None

# --- 選科目 ---
subjects = sorted({str(q["科目"]) for q in questions if str(q.get("科目", "")).strip()})
subject = st.selectbox("選擇科目", subjects)
quiz = [q for q in questions if str(q.get("科目", "")) == subject]
st.caption(f"本次共 {len(quiz)} 題")

# --- 作答表單 ---
with st.form("quiz_form"):
    answers = {}
    for i, q in enumerate(quiz):
        answers[i] = st.radio(
            f"{i+1}. {q['題目']}",
            get_options(q),
            index=None,
            key=f"q_{i}",
        )
    submitted = st.form_submit_button("送出答案")

# --- 批改並記錄 ---
if submitted:
    score = 0
    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []
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
            now,
            str(q.get("題號", "")),
            str(q.get("題目", "")),
            str(chosen),
            "O" if is_correct else "X",
        ])
        results.append((i, q, correct, chosen, is_correct))

    log_ws.append_rows(rows)  # 一次把這組作答全部寫入

    st.subheader(f"結果：答對 {score} / {len(quiz)} 題")
    for i, q, correct, chosen, is_correct in results:
        if correct is None:
            st.warning(f"{i+1}. 這題的「正解」欄設定有誤，請檢查試算表")
        elif is_correct:
            st.success(f"{i+1}. 答對 ✔")
        else:
            st.error(f"{i+1}. 答錯 ✘　你選：{chosen}　正解：{correct}")
            if str(q.get('解析', '')).strip():
                st.caption(f"解析：{q['解析']}")
