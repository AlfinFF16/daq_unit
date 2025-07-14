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
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QStyle
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QColor
import pyqtgraph as pg
from collections import deque

# =============================================================================
#  --- APPLICATION STYLING AND CONSTANTS ---
# =============================================================================
class AppColors:
    PRIMARY = "#3498db"
    SECONDARY = "#2980b9"
    BACKGROUND_LIGHT = "#f4f6f8"
    BACKGROUND_DARK = "#eaedf1"
    TEXT_PRIMARY = "#2c3e51"
    TEXT_SECONDARY = "#7f8c8d"
    SUCCESS = "#2ecc71"
    DANGER = "#e74c3c"
    WARNING = "#f39c12"
    BORDER = "#bdc3c7"

APP_STYLESHEET = f"""
    /* ... existing styles ... */
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
        
        # Logging state
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

    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(cmd.encode('utf-8'))
            except Exception as e:
                print(f"Send command error: {e}")

    def start_logging(self, log_folder):
        self.log_folder = log_folder
        self.logging_active = True
        print(f"Logging started in thread. Folder: {self.log_folder}")

    def stop_logging(self):
        self.logging_active = False
        for f in self.log_files.values():
            f.close()
        self.log_files.clear()
        print("Logging stopped in thread.")
        
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
                except Exception as e:
                    print(f"Serial read error: {e}")

                current_time = time.time()
                if current_time - self.last_process_time > 0.1:
                    self.process_buffer()
                    self.last_process_time = current_time
            else:
                self.msleep(50)

    def process_buffer(self):
        if '\n' not in self.buffer:
            return

        data_batch = {"UART1": [], "UART2": [], "UART3": [], "UART4": []}
        
        # Split buffer at last newline
        if '\n' in self.buffer:
            lines, self.buffer = self.buffer.rsplit('\n', 1)
        else:
            lines = self.buffer
            self.buffer = ""
        
        for line in lines.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Extract timestamp if present
            if line.startswith('[') and ']' in line:
                end_bracket = line.find(']')
                data_content = line[end_bracket+1:].strip()
            else:
                data_content = line
            
            # Determine UART ID based on content
            if "$GPGGA" in data_content: 
                uart_id = "UART1"
            elif "$MYINS" in data_content: 
                uart_id = "UART2"
            elif "$SDDBT" in data_content: 
                uart_id = "UART3"
            else: 
                uart_id = "UART4"
            
            # Add to batch
            data_batch[uart_id].append(data_content)
            
            # Log data if enabled
            if self.logging_active:
                self.log_data(uart_id, data_content)

        # Emit non-empty batches
        non_empty_batch = {k: v for k, v in data_batch.items() if v}
        if non_empty_batch:
            self.data_received_batch.emit(non_empty_batch)

        # Safety net for buffer size
        if len(self.buffer) > 20000:
            self.buffer = self.buffer[-10000:]

    def log_data(self, uart_id, data_content):
        try:
            if uart_id not in self.log_files:
                filename = os.path.join(self.log_folder, f"{uart_id.lower()}.csv")
                self.log_files[uart_id] = open(filename, 'a', newline='', encoding='utf-8')
                writer = csv.writer(self.log_files[uart_id])
                writer.writerow(["PC Timestamp", "Raw Data"])

            pc_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            writer = csv.writer(self.log_files[uart_id])
            writer.writerow([pc_timestamp, data_content])
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
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Connection controls
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
        
        # Logging controls
        log_group = QGroupBox("Data Logging")
        log_layout = QHBoxLayout()
        self.log_status = QLabel("INACTIVE")
        self.update_log_status_style(active=False)
        log_layout.addWidget(self.log_status)
        log_layout.addStretch()
        self.log_btn = QPushButton("Start Logging")
        self.log_btn.clicked.connect(self.toggle_logging)
        self.update_log_button_style(active=False)
        self.log_btn.setEnabled(False)
        log_layout.addWidget(self.log_btn)
        log_group.setLayout(log_layout)
        
        # Add control groups to layout
        control_grid = QGridLayout()
        control_grid.addWidget(com_group, 0, 0)
        control_grid.addWidget(log_group, 0, 1)
        main_layout.addLayout(control_grid)

        # UART data displays
        uart_group = QGroupBox("Live UART Data Streams (Last 10 lines)")
        uart_layout = QGridLayout()
        self.uart_displays = {}
        
        for i in range(1, 5):
            text_edit = QPlainTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Consolas", 10))
            text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            
            self.uart_displays[f"UART{i}"] = text_edit
            
            container = QWidget()
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(5)
            label = QLabel(f"UART {i}")
            label.setStyleSheet("font-weight: bold;")
            vbox.addWidget(label)
            vbox.addWidget(text_edit)
            
            uart_layout.addWidget(container, (i-1)//2, (i-1)%2)
        
        uart_group.setLayout(uart_layout)
        main_layout.addWidget(uart_group, 1)
        
        # Connect to serial thread
        self.serial_thread.data_received_batch.connect(self.handle_serial_data_batch)
        self.update_connect_button_style(connected=False)

    def refresh_ports(self):
        self.com_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.com_combo.addItems(ports)
        else:
            self.com_combo.addItem("No ports found")

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
            if port and "No ports" not in port:
                if self.serial_thread.connect(port):
                    self.serial_thread.start()
                    self.update_connect_button_style(connected=True)
                    self.refresh_btn.setEnabled(False)

    def update_log_status_style(self, active):
        if active:
            self.log_status.setText("ACTIVE")
            self.log_status.setStyleSheet(f"color: {AppColors.SUCCESS}; font-weight: bold;")
        else:
            self.log_status.setText("INACTIVE")
            self.log_status.setStyleSheet(f"color: {AppColors.DANGER}; font-weight: bold;")

    def update_log_button_style(self, active):
        if active:
            self.log_btn.setText("Stop Logging")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.DANGER};")
        else:
            self.log_btn.setText("Start Logging")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.PRIMARY};")

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
                self.data_buffers[uart_id].extend(data_list)

    def update_displays(self):
        for uart_id, display in self.uart_displays.items():
            buffer = self.data_buffers[uart_id]
            if buffer:
                display_text = "\n".join(buffer)
                display.setPlainText(display_text)

# =============================================================================
#  --- MONITORING PAGE ---
# =============================================================================
class MonitoringPage(QWidget):
    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.depth_data = deque(maxlen=100)
        self.roll_data = deque(maxlen=100)
        self.pitch_data = deque(maxlen=100)
        self.heading_data = deque(maxlen=100)
        self.timestamps = deque(maxlen=100)
        self.last_update = 0

        self.init_ui()
        serial_thread.data_received_batch.connect(self.process_data_batch)

    def _create_param_box(self, title, subtitle):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignCenter)
        value_label = QLabel("---")
        value_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(f"color: {AppColors.TEXT_PRIMARY};")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(f"color: {AppColors.TEXT_SECONDARY};")
        layout.addWidget(value_label)
        layout.addWidget(subtitle_label)
        return group, value_label

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # Status indicator
        self.status_label = QLabel("Awaiting data...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-weight: bold; color: #666;")
        main_layout.addWidget(self.status_label)
        
        # Instrument mapping
        mapping_group = QGroupBox("Instrument Port Mapping")
        mapping_layout = QVBoxLayout(mapping_group)
        self.table = QTableWidget(4, 2)
        self.table.setHorizontalHeaderLabels(["Port", "Assigned Instrument"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        instruments = [
            ("UART1", "GPS Position (GPGGA)"),
            ("UART2", "INS (Roll/Pitch/Heading)"),
            ("UART3", "Depth Sensor (SDDBT)"),
            ("UART4", "Reserved")
        ]
        for row, (port, desc) in enumerate(instruments):
            self.table.setItem(row, 0, QTableWidgetItem(port))
            self.table.setItem(row, 1, QTableWidgetItem(desc))
        mapping_layout.addWidget(self.table)
        main_layout.addWidget(mapping_group)
        
        # Data display
        data_group = QGroupBox("Live Sensor Measurements")
        grid_layout = QGridLayout(data_group)
        grid_layout.setSpacing(15)
        param_defs = [
            ("GPS Time", "UTC"), 
            ("Position", "Latitude, Longitude"), 
            ("Attitude", "Roll, Pitch, Heading (°)"),
            ("Depth", "Below Transducer (m)")
        ]
        self.param_labels = {}
        for i, (title, subtitle) in enumerate(param_defs):
            box, label = self._create_param_box(title, subtitle)
            grid_layout.addWidget(box, i // 2, i % 2)
            self.param_labels[title] = label
        main_layout.addWidget(data_group)
        
        # Graphs
        graph_group = QGroupBox("Sensor History")
        graph_layout = QVBoxLayout(graph_group)
        
        # Depth graph
        depth_graph = QWidget()
        depth_layout = QVBoxLayout(depth_graph)
        depth_layout.addWidget(QLabel("Depth History"))
        self.depth_plot = pg.PlotWidget()
        self.depth_plot.setBackground('w')
        self.depth_plot.setLabel('left', "Depth (m)")
        self.depth_plot.setLabel('bottom', "Time")
        self.depth_plot.showGrid(x=True, y=True, alpha=0.3)
        self.depth_curve = self.depth_plot.plot(pen=pg.mkPen(color='b', width=2))
        depth_layout.addWidget(self.depth_plot)
        
        # Attitude graph
        attitude_graph = QWidget()
        attitude_layout = QVBoxLayout(attitude_graph)
        attitude_layout.addWidget(QLabel("Attitude History"))
        self.attitude_plot = pg.PlotWidget()
        self.attitude_plot.setBackground('w')
        self.attitude_plot.setLabel('left', "Degrees")
        self.attitude_plot.setLabel('bottom', "Time")
        self.attitude_plot.showGrid(x=True, y=True, alpha=0.3)
        self.roll_curve = self.attitude_plot.plot(pen=pg.mkPen(color='r', width=2), name="Roll")
        self.pitch_curve = self.attitude_plot.plot(pen=pg.mkPen(color='g', width=2), name="Pitch")
        self.heading_curve = self.attitude_plot.plot(pen=pg.mkPen(color='b', width=2), name="Heading")
        self.attitude_plot.addLegend()
        attitude_layout.addWidget(self.attitude_plot)
        
        # Add graphs to layout
        graph_layout.addWidget(depth_graph)
        graph_layout.addWidget(attitude_graph)
        main_layout.addWidget(graph_group)
        
        # Setup graph update timer
        self.graph_timer = QTimer(self)
        self.graph_timer.timeout.connect(self.update_graphs)
        self.graph_timer.start(500)

    def process_data_batch(self, data_batch):
        current_time = time.time()
        for uart_id, data_list in data_batch.items():
            if data_list:
                self.process_data(uart_id, data_list[-1])
        
        # Update status
        time_since_last = current_time - self.last_update
        if time_since_last > 5:
            self.status_label.setText("No data received recently")
            self.status_label.setStyleSheet("font-weight: bold; color: #e74c3c;")
        elif time_since_last > 2:
            self.status_label.setText("Data connection slow")
            self.status_label.setStyleSheet("font-weight: bold; color: #f39c12;")
        else:
            self.status_label.setText("Receiving data")
            self.status_label.setStyleSheet("font-weight: bold; color: #2ecc71;")
            
        self.last_update = current_time

    def process_data(self, uart_id, data):
        try:
            if uart_id == "UART1" and data.startswith('$GPGGA'):
                parts = data.split(',')
                if len(parts) > 9 and parts[1] and parts[2] and parts[4]:
                    # Parse time
                    time_str = parts[1]
                    if '.' in time_str:
                        time_str = time_str.split('.')[0]
                    try:
                        hours = time_str[0:2]
                        minutes = time_str[2:4]
                        seconds = time_str[4:6]
                        time_formatted = f"{hours}:{minutes}:{seconds}"
                        self.param_labels["GPS Time"].setText(time_formatted)
                    except:
                        pass
                    
                    # Parse latitude
                    lat_str = parts[2]
                    lat_dir = parts[3]
                    try:
                        lat_deg = float(lat_str[0:2])
                        lat_min = float(lat_str[2:])
                        latitude = lat_deg + (lat_min / 60)
                        if lat_dir == 'S':
                            latitude = -latitude
                    except ValueError:
                        latitude = 0.0
                    
                    # Parse longitude
                    lon_str = parts[4]
                    lon_dir = parts[5]
                    try:
                        lon_deg = float(lon_str[0:3])
                        lon_min = float(lon_str[3:])
                        longitude = lon_deg + (lon_min / 60)
                        if lon_dir == 'W':
                            longitude = -longitude
                    except ValueError:
                        longitude = 0.0
                    
                    self.param_labels["Position"].setText(f"{latitude:.6f}, {longitude:.6f}")
            
            elif uart_id == "UART2" and data.startswith('$MYINS'):
                parts = data.split(',')
                if len(parts) >= 4:
                    roll = parts[1].split('*')[0].strip()
                    pitch = parts[2].split('*')[0].strip()
                    heading = parts[3].split('*')[0].strip()
                    
                    self.param_labels["Attitude"].setText(f"R: {roll}°  P: {pitch}°  H: {heading}°")
                    
                    try:
                        self.roll_data.append(float(roll))
                        self.pitch_data.append(float(pitch))
                        self.heading_data.append(float(heading))
                        self.timestamps.append(time.time())
                    except ValueError:
                        pass
            
            elif uart_id == "UART3" and data.startswith('$SDDBT'):
                parts = data.split(',')
                if len(parts) >= 4:
                    depth = parts[3].split('*')[0].strip()
                    self.param_labels["Depth"].setText(f"{depth} m")
                    try:
                        self.depth_data.append(float(depth))
                    except ValueError:
                        pass
        
        except (ValueError, IndexError, TypeError) as e:
            print(f"Error processing data: {e}")

    def update_graphs(self):
        if self.depth_data:
            self.depth_curve.setData(list(self.depth_data))
        
        if self.roll_data and self.pitch_data and self.heading_data and self.timestamps:
            if self.timestamps:
                base_time = self.timestamps[0]
                rel_times = [t - base_time for t in self.timestamps]
                self.roll_curve.setData(rel_times, list(self.roll_data))
                self.pitch_curve.setData(rel_times, list(self.pitch_data))
                self.heading_curve.setData(rel_times, list(self.heading_data))

# =============================================================================
#  --- MAIN WINDOW ---
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hydrographic DAQ & Monitoring System")
        self.setWindowIcon(QIcon(self.style().standardIcon(QStyle.SP_ComputerIcon)))
        self.setGeometry(50, 50, 1280, 800)
        
        self.serial_thread = SerialThread()
        
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setMovable(False)
        
        self.main_page = MainPage(self.serial_thread)
        self.monitoring_page = MonitoringPage(self.serial_thread)
        
        self.tabs.addTab(self.main_page, "Logging")
        self.tabs.addTab(self.monitoring_page, "Monitoring")
        
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())