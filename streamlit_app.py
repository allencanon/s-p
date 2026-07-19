import streamlit as st

st.set_page_config(page_title="我的學習小站", page_icon="📚")

st.title("📚 我的學習小站")
st.write("歡迎回來！今天先來一題暖身：")

question = "台灣最高的山是哪一座？"
options = ["玉山", "雪山", "合歡山", "阿里山"]
answer = "玉山"

choice = st.radio(question, options, index=None)

if st.button("送出答案"):
    if choice is None:
        st.warning("先選一個答案喔！")
    elif choice == answer:
        st.success("答對了！🎉")
    else:
        st.error(f"再想想～正確答案是：{answer}")
