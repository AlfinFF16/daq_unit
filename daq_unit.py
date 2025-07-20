import sys
import os
import csv
import serial
import time
import serial.tools.list_ports
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QPlainTextEdit, QGroupBox, QGridLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QStyle, QSizePolicy
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QFontDatabase
import pyqtgraph as pg
from collections import deque

# =============================================================================
#  --- APPLICATION STYLING AND CONSTANTS ---
# =============================================================================
class AppColors:
    BACKGROUND = "#1e1f22"
    HEADER_BACKGROUND = "#101113"
    PRIMARY = "#0078D7"
    SECONDARY = "#2ecc71"
    TEXT_PRIMARY = "#e0e0e0"
    TEXT_SECONDARY = "#a0a0a0"
    BORDER = "#323336"
    SUCCESS = "#2ecc71"
    DANGER = "#e74c3c"
    WARNING = "#f39c12"

# Updated stylesheet with tab styling and spacing improvements
APP_STYLESHEET = f"""
    QWidget {{
        color: {AppColors.TEXT_PRIMARY};
        font-family: "Segoe UI", Arial, sans-serif;
        spacing: 8px;
    }}
    QMainWindow {{
        background-color: {AppColors.BACKGROUND};
    }}
    QTabWidget::pane {{
        border: none;
        background-color: {AppColors.BACKGROUND};
        border-top: 2px solid {AppColors.PRIMARY};
        margin-top: -1px;
    }}
    QGroupBox {{
        background-color: #28292c;
        border: 1px solid {AppColors.BORDER};
        border-radius: 8px;
        margin-top: 1ex;
        font-weight: bold;
        font-size: 11pt;
        padding: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top center;
        padding: 0 10px;
    }}
    QPushButton {{
        background-color: {AppColors.PRIMARY};
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-weight: bold;
        margin: 5px;
    }}
    QPushButton:hover {{
        background-color: #1088E7;
    }}
    QPushButton:disabled {{
        background-color: #555;
        color: #999;
    }}
    QComboBox {{
        background-color: #2c2d30;
        border: 1px solid {AppColors.BORDER};
        padding: 5px;
        border-radius: 4px;
        margin: 5px;
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QPlainTextEdit {{
        background-color: #2c2d30;
        border: 1px solid {AppColors.BORDER};
        border-radius: 4px;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 10pt;
        padding: 8px;
    }}
    QTabWidget::tab-bar {{
        alignment: center;
    }}
    QTabBar::tab {{
        background: #28292c;
        min-width: 120px;
        max-width: 200px;
        height: 35px;
        padding: 8px 20px;
        margin: 0 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-weight: bold;
        font-size: 11pt;
        border: 1px solid {AppColors.BORDER};
    }}
    QTabBar::tab:selected {{
        background: {AppColors.PRIMARY};
        color: white;
        border-bottom: 2px solid {AppColors.PRIMARY};
    }}
    QTabBar::tab:hover:!selected {{
        background: #323336;
    }}
    QTableWidget {{
        background-color: #2c2d30;
        border: 1px solid {AppColors.BORDER};
        gridline-color: {AppColors.BORDER};
    }}
    QHeaderView::section {{
        background-color: #323336;
        padding: 4px;
        border: 1px solid {AppColors.BORDER};
        font-weight: bold;
    }}
    QLabel {{
        margin: 5px;
    }}
    QTableWidget::item {{
        padding: 6px;
    }}
"""

# =============================================================================
#  --- OPTIMIZED SERIAL THREAD ---
# =============================================================================
class SerialThread(QThread):
    data_received_batch = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.buffer = ""
        self.last_process_time = time.time()
        self.logging_active = False
        self.log_files = {}
        self.log_folder = ""

    def connect(self, port):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        try:
            self.serial_port = serial.Serial(port, baudrate=115200, timeout=0.1)
            self.running = True
            self.buffer = ""
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        self.running = False
        self.stop_logging()
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.wait()

    def start_logging(self, log_folder):
        self.log_folder = log_folder
        self.logging_active = True

    def stop_logging(self):
        self.logging_active = False
        for f in self.log_files.values():
            f.close()
        self.log_files.clear()

    def run(self):
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    data = self.serial_port.read(self.serial_port.in_waiting or 1)
                    if data:
                        self.buffer += data.decode('ascii', errors='ignore')
                except serial.SerialException as e:
                    print(f"Serial port disconnected or error: {e}")
                    self.running = False
                    break

                current_time = time.time()
                if current_time - self.last_process_time > 0.1:
                    self.process_buffer()
                    self.last_process_time = current_time
            else:
                self.msleep(50)

    def process_buffer(self):
        if '\n' not in self.buffer:
            return

        lines, self.buffer = self.buffer.rsplit('\n', 1)
        data_batch = {"UART1": [], "UART2": [], "UART3": [], "UART4": []}

        for line in lines.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Extract UART port and timestamp from DAQ format
            uart_id = None
            device_timestamp = ""
            data_content = line
            
            # Parse DAQ format: [UARTx][HH:MM:SS.ffffff] $DATA
            if line.startswith('[') and ']' in line:
                parts = line.split(']', 2)
                if len(parts) >= 3:
                    # Extract UART ID from first part: [UART1
                    uart_part = parts[0][1:]  # Remove leading '['
                    if uart_part.startswith("UART"):
                        uart_id = uart_part
                    
                    # Extract timestamp from second part: [17:09:21.256293
                    time_part = parts[1][1:]  # Remove leading '['
                    if ':' in time_part and '.' in time_part:
                        device_timestamp = time_part
                    
                    # The rest is the actual data content
                    data_content = parts[2].strip()
            
            # If UART ID wasn't parsed, determine from content
            if uart_id is None:
                if "$GPGGA" in data_content: uart_id = "UART1"
                elif "$MYINS" in data_content: uart_id = "UART2"
                elif "$SDDBT" in data_content: uart_id = "UART3"
                else: continue

            # Store both timestamp and content
            data_batch[uart_id].append((device_timestamp, data_content))
            
            if self.logging_active:
                self.log_data(uart_id, device_timestamp, data_content)

        non_empty_batch = {k: v for k, v in data_batch.items() if v}
        if non_empty_batch:
            self.data_received_batch.emit(non_empty_batch)

    def log_data(self, uart_id, device_timestamp, data_content):
        try:
            if uart_id not in self.log_files:
                filename = os.path.join(self.log_folder, f"{uart_id.lower()}.csv")
                self.log_files[uart_id] = open(filename, 'a', newline='', encoding='utf-8')
                writer = csv.writer(self.log_files[uart_id])
                # Header with DEVICE timestamp
                writer.writerow(["Device Timestamp", "Raw Data"])

            writer = csv.writer(self.log_files[uart_id])
            writer.writerow([device_timestamp, data_content])
        except (IOError, csv.Error) as e:
            print(f"Error writing to log for {uart_id}: {e}")

# =============================================================================
#  --- MAIN LOGGING PAGE ---
# =============================================================================
class MainPage(QWidget):
    DISPLAY_LINE_COUNT = 10

    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.logging_active = False
        self.data_buffers = {
            f"UART{i}": deque(maxlen=self.DISPLAY_LINE_COUNT) for i in range(1, 5)
        }
        self.init_ui()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_displays)
        self.update_timer.start(100)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        control_grid = QGridLayout()
        com_group = QGroupBox("Serial Connection")
        com_layout = QHBoxLayout()
        com_layout.addWidget(QLabel("COM Port:"))
        self.com_combo = QComboBox()
        self.refresh_ports()
        com_layout.addWidget(self.com_combo, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        com_layout.addWidget(self.refresh_btn)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        com_layout.addWidget(self.connect_btn)
        com_group.setLayout(com_layout)
        com_group.setContentsMargins(10, 15, 10, 15)

        log_group = QGroupBox("Data Logging")
        log_layout = QHBoxLayout()
        self.log_status = QLabel("INACTIVE")
        self.update_log_status_style(active=False)
        log_layout.addWidget(self.log_status)
        log_layout.addStretch()
        self.log_btn = QPushButton("Start Logging")
        self.log_btn.clicked.connect(self.toggle_logging)
        self.log_btn.setEnabled(False)
        log_layout.addWidget(self.log_btn)
        log_group.setLayout(log_layout)
        log_group.setContentsMargins(10, 15, 10, 15)

        control_grid.addWidget(com_group, 0, 0)
        control_grid.addWidget(log_group, 0, 1)
        main_layout.addLayout(control_grid)

        uart_group = QGroupBox("Live UART Data Streams (Last 10 lines)")
        uart_layout = QGridLayout()
        uart_layout.setSpacing(15)
        self.uart_displays = {}
        for i in range(1, 5):
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(8)
            
            label = QLabel(f"UART {i}")
            label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
            
            text_edit = QPlainTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setMinimumHeight(150)
            
            vbox.addWidget(label)
            vbox.addWidget(text_edit)
            
            self.uart_displays[f"UART{i}"] = text_edit
            uart_layout.addWidget(container, (i - 1) // 2, (i - 1) % 2)
        
        uart_group.setLayout(uart_layout)
        uart_group.setContentsMargins(15, 20, 15, 15)
        main_layout.addWidget(uart_group, 1)

        self.serial_thread.data_received_batch.connect(self.handle_serial_data_batch)
        self.update_connect_button_style(connected=False)

    def refresh_ports(self):
        self.com_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.com_combo.addItems(ports if ports else ["No ports found"])

    def update_connect_button_style(self, connected):
        if connected:
            self.connect_btn.setText("Disconnect")
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.DANGER};")
            self.log_btn.setEnabled(True)
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.SUCCESS};")
            self.log_btn.setEnabled(False)
            if self.logging_active:
                self.toggle_logging()

    def toggle_connection(self):
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect()
            self.update_connect_button_style(connected=False)
            self.refresh_btn.setEnabled(True)
        else:
            port = self.com_combo.currentText()
            if "No ports" not in port and self.serial_thread.connect(port):
                self.serial_thread.start()
                self.update_connect_button_style(connected=True)
                self.refresh_btn.setEnabled(False)

    def update_log_status_style(self, active):
        self.log_status.setText("ACTIVE" if active else "INACTIVE")
        color = AppColors.SUCCESS if active else AppColors.DANGER
        self.log_status.setStyleSheet(f"color: {color}; font-weight: bold; font-size:10pt;")

    def update_log_button_style(self, active):
        self.log_btn.setText("Stop Logging" if active else "Start Logging")
        color = AppColors.DANGER if active else AppColors.PRIMARY
        self.log_btn.setStyleSheet(f"background-color: {color};")

    def toggle_logging(self):
        self.logging_active = not self.logging_active
        self.update_log_status_style(self.logging_active)
        self.update_log_button_style(self.logging_active)
        if self.logging_active:
            log_folder = datetime.now().strftime("%Y%m%d_%H%M%S_logs")
            os.makedirs(log_folder, exist_ok=True)
            self.serial_thread.start_logging(log_folder)
        else:
            self.serial_thread.stop_logging()

    def handle_serial_data_batch(self, data_batch):
        for uart_id, data_list in data_batch.items():
            if uart_id in self.data_buffers:
                for timestamp, data_item in data_list:
                    # Use device timestamp if available
                    if timestamp:
                        formatted_line = f"[{timestamp}] {data_item}"
                    else:
                        formatted_line = data_item
                    self.data_buffers[uart_id].append(formatted_line)

    def update_displays(self):
        for uart_id, display in self.uart_displays.items():
            buffer = self.data_buffers[uart_id]
            if buffer:
                display.setPlainText("\n".join(buffer))
                display.verticalScrollBar().setValue(display.verticalScrollBar().maximum())

# =============================================================================
#  --- MONITORING PAGE ---
# =============================================================================
class MonitoringPage(QWidget):
    data_updated = pyqtSignal(dict)

    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.last_update = 0
        self.data = {
            "time": "---", "lat": 0.0, "lon": 0.0, "depth": 0.0,
            "roll": 0.0, "pitch": 0.0, "heading": 0.0
        }
        self.history = {
            "depth": deque(maxlen=100), "roll": deque(maxlen=100),
            "pitch": deque(maxlen=100), "heading": deque(maxlen=100),
            "time": deque(maxlen=100)
        }
        self.init_ui()
        self.serial_thread.data_received_batch.connect(self.process_data_batch)
        self.data_updated.connect(self.update_ui)

    def _create_param_box(self, title, subtitle):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 15, 10, 15)
        
        value_label = QLabel("---")
        value_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet("margin-bottom: 5px;")
        
        subtitle_label = QLabel(subtitle)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(f"color: {AppColors.TEXT_SECONDARY};")
        
        layout.addWidget(value_label)
        layout.addWidget(subtitle_label)
        return group, value_label

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        top_layout = QHBoxLayout()
        mapping_group = QGroupBox("Instrument Port Mapping")
        mapping_layout = QVBoxLayout(mapping_group)
        mapping_layout.setContentsMargins(10, 15, 10, 15)
        
        self.table = QTableWidget(4, 2)
        self.table.setHorizontalHeaderLabels(["Port", "Assigned Instrument"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(180)
        instruments = [
            ("UART1", "GPS Position (GPGGA)"), ("UART2", "INS (Roll/Pitch/Heading)"),
            ("UART3", "Depth Sensor (SDDBT)"), ("UART4", "Reserved")
        ]
        for row, (port, desc) in enumerate(instruments):
            self.table.setItem(row, 0, QTableWidgetItem(port))
            self.table.setItem(row, 1, QTableWidgetItem(desc))
        mapping_layout.addWidget(self.table)
        top_layout.addWidget(mapping_group, 1)

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout(status_group)
        status_layout.setContentsMargins(10, 15, 10, 15)
        
        self.status_label = QLabel("Awaiting data...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        top_layout.addWidget(status_group, 1)
        main_layout.addLayout(top_layout)

        data_group = QGroupBox("Live Sensor Measurements")
        grid_layout = QGridLayout(data_group)
        grid_layout.setSpacing(15)
        grid_layout.setContentsMargins(10, 15, 10, 15)
        
        param_defs = [
            ("GPS Time", "UTC"), ("Position", "Latitude, Longitude"),
            ("Attitude", "Roll, Pitch, Heading (°)"), ("Depth", "Below Transducer (m)")
        ]
        self.param_labels = {}
        for i, (title, subtitle) in enumerate(param_defs):
            box, label = self._create_param_box(title, subtitle)
            grid_layout.addWidget(box, i // 2, i % 2)
            self.param_labels[title] = label
        main_layout.addWidget(data_group)

        graph_group = QGroupBox("Sensor History")
        graph_layout = QGridLayout(graph_group)
        graph_layout.setContentsMargins(10, 15, 10, 15)
        graph_layout.setSpacing(15)

        pg.setConfigOption('background', AppColors.BACKGROUND)
        pg.setConfigOption('foreground', AppColors.TEXT_PRIMARY)

        self.depth_plot = pg.PlotWidget(title="Depth History")
        self.depth_plot.setLabel('left', "Depth (m)")
        self.depth_plot.showGrid(x=True, y=True, alpha=0.3)
        self.depth_curve = self.depth_plot.plot(pen=pg.mkPen(color='#00AEEF', width=2))
        graph_layout.addWidget(self.depth_plot, 0, 0)

        self.attitude_plot = pg.PlotWidget(title="Attitude History")
        self.attitude_plot.setLabel('left', "Degrees")
        self.attitude_plot.addLegend(offset=(-10, 10))
        self.attitude_plot.showGrid(x=True, y=True, alpha=0.3)
        self.roll_curve = self.attitude_plot.plot(pen=pg.mkPen(color='#E32252', width=2), name="Roll")
        self.pitch_curve = self.attitude_plot.plot(pen=pg.mkPen(color='#32E389', width=2), name="Pitch")
        self.heading_curve = self.attitude_plot.plot(pen=pg.mkPen(color='#A259FF', width=2), name="Heading")
        graph_layout.addWidget(self.attitude_plot, 0, 1)
        main_layout.addWidget(graph_group, 1)

    def process_data_batch(self, data_batch):
        for uart_id, data_list in data_batch.items():
            if data_list:
                # Process only the last item in the batch
                _, last_data = data_list[-1]
                self.process_data(uart_id, last_data)

        time_since_last = time.time() - self.last_update
        if time_since_last > 5:
            self.status_label.setText("No data received")
            self.status_label.setStyleSheet(f"color: {AppColors.DANGER}; font-size: 16px; font-weight: bold;")
        elif time_since_last > 2:
            self.status_label.setText("Connection slow")
            self.status_label.setStyleSheet(f"color: {AppColors.WARNING}; font-size: 16px; font-weight: bold;")
        else:
            self.status_label.setText("Receiving data")
            self.status_label.setStyleSheet(f"color: {AppColors.SUCCESS}; font-size: 16px; font-weight: bold;")

        self.data_updated.emit(self.data)

    def process_data(self, uart_id, data):
        try:
            parts = data.split('*')[0].split(',')
            if uart_id == "UART1" and data.startswith('$GPGGA') and len(parts) > 5:
                if parts[1]:
                    t = parts[1]
                    self.data['time'] = f"{t[0:2]}:{t[2:4]}:{t[4:6]}"
                if parts[2] and parts[3] and parts[4] and parts[5]:
                    lat_str, lat_dir = parts[2], parts[3]
                    lon_str, lon_dir = parts[4], parts[5]
                    lat = float(lat_str[:2]) + float(lat_str[2:]) / 60
                    if lat_dir == 'S': lat = -lat
                    lon = float(lon_str[:3]) + float(lon_str[3:]) / 60
                    if lon_dir == 'W': lon = -lon
                    self.data['lat'], self.data['lon'] = lat, lon

            elif uart_id == "UART2" and data.startswith('$MYINS') and len(parts) >= 4:
                self.data['roll'] = float(parts[1])
                self.data['pitch'] = float(parts[2])
                self.data['heading'] = float(parts[3])
                self.history['roll'].append(self.data['roll'])
                self.history['pitch'].append(self.data['pitch'])
                self.history['heading'].append(self.data['heading'])
                self.history['time'].append(time.time())

            elif uart_id == "UART3" and data.startswith('$SDDBT') and len(parts) >= 4:
                self.data['depth'] = float(parts[3])
                self.history['depth'].append(self.data['depth'])

            self.last_update = time.time()
        except (ValueError, IndexError) as e:
            print(f"Error parsing {uart_id} data: {data} -> {e}")

    def update_ui(self, data):
        self.param_labels["GPS Time"].setText(data['time'])
        self.param_labels["Position"].setText(f"{data['lat']:.6f}, {data['lon']:.6f}")
        self.param_labels["Depth"].setText(f"{data['depth']:.2f} m")
        self.param_labels["Attitude"].setText(f"R:{data['roll']:.2f}° P:{data['pitch']:.2f}° H:{data['heading']:.2f}°")

        self.depth_curve.setData(list(self.history['depth']))
        if self.history['time']:
            time_x = [t - self.history['time'][0] for t in self.history['time']]
            self.roll_curve.setData(time_x, list(self.history['roll']))
            self.pitch_curve.setData(time_x, list(self.history['pitch']))
            self.heading_curve.setData(time_x, list(self.history['heading']))


# =============================================================================
#  --- MAIN WINDOW ---
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hydrographic DAQ & Monitoring System")
        self.setWindowIcon(QIcon(self.style().standardIcon(QStyle.SP_ComputerIcon)))
        self.setGeometry(50, 50, 1440, 900)
        self.serial_thread = SerialThread()

        # Main container widget
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(f"background-color: {AppColors.HEADER_BACKGROUND}; border-bottom: 2px solid {AppColors.PRIMARY};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 12, 20, 12)
        title_label = QLabel("Hydrographic DAQ & Monitoring System")
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        main_layout.addWidget(header)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.main_page = MainPage(self.serial_thread)
        self.monitoring_page = MonitoringPage(self.serial_thread)
        self.tabs.addTab(self.main_page, "Logging")
        self.tabs.addTab(self.monitoring_page, "Monitoring")
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)

    def closeEvent(self, event):
        self.serial_thread.disconnect()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())