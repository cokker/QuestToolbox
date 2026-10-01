def stylesheet(light=False):
    bg, panel, field, line, fg, muted = ('#f3f5fa','#ffffff','#f0f2f8','#d9dfeb','#182339','#53627a') if light else ('#0c111b','#141d2c','#0e1624','#27354b','#eaf0fa','#98a9c2')
    return f'''
    QWidget {{ color:{fg}; font-family:"Segoe UI", "DejaVu Sans"; font-size:13px; }}
    QMainWindow, QDialog, #root, #page {{ background:{bg}; }}
    #sidebar, #card {{ background:{panel}; border:1px solid {line}; border-radius:16px; }}
    #brand {{ font-size:24px; font-weight:700; }}
    #title {{ font-size:27px; font-weight:700; }}
    #hero {{ font-size:32px; font-weight:700; }}
    #muted {{ color:{muted}; }}
    #eyebrow {{ color:#67cce8; font-size:11px; font-weight:700; }}
    #stat {{ font-size:26px; font-weight:600; }}
    QLabel {{ background:transparent; }}
    QPushButton {{ background:{panel}; border:1px solid {line}; border-radius:9px; padding:10px 15px; }}
    QPushButton:hover {{ border-color:#6ea9d7; background:{field}; }}
    QPushButton:pressed {{ background:#284568; }}
    QPushButton:disabled {{ color:{muted}; border-color:{line}; }}
    QPushButton[primary="true"] {{ background:#ff9b54; color:#152032; border:0; font-weight:700; }}
    QPushButton[primary="true"]:hover {{ background:#ffb376; }}
    QPushButton[primary="true"]:disabled {{ background:{line}; color:{muted}; }}
    QPushButton[danger="true"] {{ color:#ff8f99; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background:{field}; border:1px solid {line}; border-radius:8px; padding:9px; selection-background-color:#315a80; }}
    QComboBox QAbstractItemView {{ background:{panel}; color:{fg}; selection-background-color:#315a80; }}
    QListWidget {{ background:transparent; border:0; outline:none; }}
    QListWidget::item {{ padding:13px; border-radius:9px; margin:2px; }}
    QListWidget::item:selected {{ background:#263c56; color:#ffffff; }}
    QTableWidget {{ background:{field}; border:1px solid {line}; border-radius:10px; gridline-color:{line}; selection-background-color:#284563; }}
    QHeaderView::section {{ background:{panel}; border:0; padding:10px; color:{muted}; }}
    QScrollArea {{ border:0; background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:11px; margin:0; }}
    QScrollBar::handle:vertical {{ background:#42536b; border-radius:5px; min-height:30px; }}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{ background:transparent; }}
    QProgressBar {{ border:0; background:{field}; border-radius:4px; height:6px; }}
    QProgressBar::chunk {{ background:#ff9b54; border-radius:4px; }}
    QCheckBox {{ spacing:8px; padding:4px; }}
    QToolTip {{ background:{panel}; color:{fg}; border:1px solid {line}; padding:6px; }}
    '''
