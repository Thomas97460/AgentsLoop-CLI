"""Textual stylesheet for the workflow TUI."""

APP_CSS = """
/* Base Styles using theme variables */
Screen {
    background: $background;
    color: $foreground;
}

.page {
    height: 100%;
    padding: 1 4 1 4;
}

/* Header & Home Logo */
.home-header {
    height: 14;
    margin-bottom: 1;
    align: center middle;
}

.home-logo {
    height: 10;
    width: 100%;
}

.text-muted {
    color: $foreground 50%;
}

/* Forms & Panels */
.panel {
    background: $panel;
    border: round $primary;
    padding: 1 2;
}

.field-label {
    height: 1;
    margin-top: 1;
    color: $primary;
    text-style: bold;
}

Input, Select, TextArea {
    margin-top: 1;
    background: $surface;
    border: tall $primary 40%;
    color: $foreground;
}

Input:focus, Select:focus, TextArea:focus {
    border: tall $primary;
}

/* Tables */
.table-container {
    height: 1fr;
}

.table-title {
    color: $primary;
    text-style: bold;
    height: 1;
    margin-bottom: 0;
    opacity: 0.8;
}

DataTable {
    background: $surface;
    color: $foreground;
    border: none;
    height: 1fr;
}

DataTable > .datatable--cursor {
    background: $primary 20%;
    color: $foreground;
    text-style: bold;
}

/* Footer / Hints */
.home-footer {
    height: 1;
    margin-top: 1;
}

.home-hints {
    color: $foreground 40%;
}

Footer {
    background: $background;
    height: 3;
    dock: bottom;
}

#launch-grid {
    layout: horizontal;
    height: 1fr;
    width: 100%;
}

#launch-main {
    width: 3fr;
    height: 100%;
    margin-right: 1;
}

#launch-side {
    width: 2fr;
    height: 100%;
    align: left top;
    overflow-y: auto;
    scrollbar-gutter: stable;
}

.actions {
    height: auto;
    width: 100%;
    align: right middle;
    padding: 1 0 0 0;
}

.actions Button {
    margin-left: 2;
}

.centered-actions {
    align: center middle;
}

TextArea#request {
    height: 1fr;
    min-height: 5;
    margin-bottom: 1;
}

#workflow-top {
    height: 3fr;
    width: 100%;
}

#workflow-nodes-panel {
    width: 2fr;
    height: 100%;
    margin-right: 2;
}

#workflow-side-panel {
    width: 3fr;
    height: 100%;
}

#workflow-report-panel {
    height: 1fr;
    width: 100%;
    background: $panel;
    border: round $primary 40%;
    padding: 1 2;
}

#report {
    height: 100%;
    width: 100%;
    overflow-y: scroll;
    scrollbar-gutter: stable;
}

#workflow-bottom {
    height: 1fr;
    width: 100%;
    margin-top: 1;
    border-top: solid $primary 20%;
}

/* Ensure Select internal text is visible */
Select > .select--current {
    color: $foreground;
}

Select:focus > .select--current {
    color: $primary;
    text-style: bold;
}

RichLog {
    height: 1fr;
    background: $surface;
    border: none;
    padding: 0 1;
    color: $foreground;
}

RichLog:focus {
    border: none;
}

.loading-container {
    align: center middle;
    height: 100%;
}

#loader {
    margin: 2 0;
    height: 3;
}

#loading-status {
    text-align: center;
    width: 100%;
    margin-bottom: 1;
}

.error-text {
    color: $error;
    text-align: center;
    width: 80%;
    margin-bottom: 2;
}

.hidden {
    display: none;
}

#loading-actions {
    width: auto;
    align: center middle;
}

.warning-container {
    align: center middle;
    height: 100%;
}

.warning-panel {
    width: 60%;
    height: auto;
    background: $panel;
    border: double $error;
    padding: 2 4;
    align: center middle;
}

.warning-title {
    color: $error;
    text-style: bold;
    margin-bottom: 1;
    width: 100%;
    text-align: center;
}

.warning-text {
    margin-bottom: 2;
    text-align: center;
    width: 100%;
}
"""
