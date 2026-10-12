import streamlit as st

def get_status_color(status):
    # Brand-neutral palette (from references/palette.md)
    # Using placeholders that are accessible
    colors = {
        "target_reached": "#1a73e8", # Blue
        "target_not_reached": "#5f6368", # Grey
        "error": "#d93025", # Red
        "fresh": "#1e8e3e", # Green
        "stale": "#f9ab00", # Yellow
    }
    return colors.get(status, "#000000")

def status_badge(status, text):
    color = get_status_color(status)
    return f'<span style="color:{color}; font-weight:bold;">{text}</span>'
