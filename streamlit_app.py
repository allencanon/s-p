import streamlit as st
import gspread
from google.oauth2 import service_account
from datetime import datetime
import json

st.set_page_config(page_title="我的學習小站", page_icon="📚")

# --- 連接 Google Sheets ---
@st.cache_resource
def get_worksheet():
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
    return sh.worksheet("作答紀錄")

worksheet = get_worksheet()

st.title("📚 我的學習小站")
st.write("歡迎回來！今天先來一題暖身：")

question = "台灣最高的山是哪一座？"
options = ["玉山", "雪山", "合歡山", "阿里山"]
answer = "玉山"

choice = st.radio(question, options, index=None)

if st.button("送出答案"):
    if choice is None:
        st.warning("先選一個答案喔！")
    else:
        is_correct = (choice == answer)
        # 把這次作答寫進 Google Sheets
        worksheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            question,
            choice,
            "O" if is_correct else "X",
        ])
        if is_correct:
            st.success("答對了！🎉（已記錄）")
        else:
            st.error(f"再想想～正確答案是：{answer}（已記錄）")

# --- 顯示最近的作答紀錄 ---
st.divider()
st.subheader("最近的作答紀錄")
records = worksheet.get_all_records()
if records:
    st.dataframe(records[-5:])
else:
    st.caption("還沒有紀錄，答一題看看吧！")
