import streamlit as st

st.navigation([
    st.Page("report_app.py", title="منشئ التقارير", icon="📝", default=True),
    st.Page("learning_app.py", title="التعلّم من كتابك", icon="📖"),
]).run()
