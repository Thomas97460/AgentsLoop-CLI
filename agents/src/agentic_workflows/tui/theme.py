"""Textual stylesheet for the workflow TUI."""

APP_CSS = """
Screen {
    background: #11120f;
    color: #ecefe7;
}

Header {
    background: #171a15;
    color: #ecefe7;
}

Footer {
    background: #171a15;
    color: #b8c1b0;
}

.page {
    height: 100%;
    padding: 1 2;
}

.hero {
    height: auto;
    margin-bottom: 1;
}

.title {
    text-style: bold;
    color: #f3c66d;
}

.subtitle {
    color: #aab7a2;
}

.section-title {
    height: 1;
    margin-top: 1;
    color: #8fd694;
    text-style: bold;
}

.form-row {
    height: auto;
    margin-top: 1;
}

.actions {
    height: auto;
    margin-top: 1;
}

DataTable {
    height: 1fr;
    background: #151811;
}

DataTable:focus {
    background-tint: #8fd694 6%;
}

Markdown {
    height: 1fr;
    padding: 0 1;
    background: #151811;
}

RichLog {
    height: 8;
    background: #151811;
    padding: 0 1;
}

Input, Select, TextArea {
    margin-top: 1;
    background: #181c14;
}

TextArea {
    height: 10;
}

Button {
    margin-right: 1;
    min-width: 14;
}

Collapsible {
    margin-top: 1;
}

LoadingIndicator {
    height: 1;
    color: #8fd694;
}

#live-grid, #detail-grid {
    layout: horizontal;
    height: 1fr;
}

#timeline {
    width: 36;
    margin-right: 1;
}

#report, #summary {
    width: 1fr;
}

#events {
    margin-top: 1;
}
"""
