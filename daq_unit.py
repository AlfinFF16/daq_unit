import sys
import os
import csv
import serial
import time
import serial.tools.list_ports
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QComboBox, QTextEdit, QPlainTextEdit, QGroupBox, QGridLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QStyle
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QColor
import pyqtgraph as pg
from collections import deque # Import deque for efficient fixed-size buffers

# =============================================================================
#  --- APPLICATION STYLING AND CONSTANTS (UNCHANGED) ---
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
    QMainWindow, QWidget {{
        background-color: {AppColors.BACKGROUND_LIGHT};
        font-family: 'Segoe UI', Arial, sans-serif;
        color: {AppColors.TEXT_PRIMARY};
    }}
    QGroupBox {{
        font-size: 11pt;
        font-weight: bold;
        color: {AppColors.PRIMARY};
        border: 1px solid {AppColors.BORDER};
        border-radius: 8px;
        margin-top: 10px;
        background-color: #ffffff;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 10px;
        left: 10px;
        background-color: {AppColors.BACKGROUND_LIGHT};
    }}
    QLabel {{
        font-size: 10pt;
    }}
    QPushButton {{
        font-size: 10pt;
        font-weight: bold;
        padding: 8px 15px;
        border-radius: 5px;
        border: 1px solid {AppColors.PRIMARY};
        background-color: {AppColors.PRIMARY};
        color: white;
    }}
    QPushButton:hover {{
        background-color: {AppColors.SECONDARY};
        border-color: {AppColors.SECONDARY};
    }}
    QPushButton:pressed {{
        background-color: {AppColors.PRIMARY};
    }}
    QPushButton:disabled {{
        background-color: {AppColors.BORDER};
        border-color: {AppColors.BORDER};
    }}
    QComboBox {{
        font-size: 10pt;
        padding: 5px;
        border: 1px solid {AppColors.BORDER};
        border-radius: 5px;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left-width: 1px;
        border-left-color: {AppColors.BORDER};
        border-left-style: solid;
        border-top-right-radius: 3px;
        border-bottom-right-radius: 3px;
    }}
    QTextEdit, QPlainTextEdit {{
        border: 1px solid {AppColors.BORDER};
        border-radius: 5px;
        background-color: #ffffff;
    }}
    QTabWidget::pane {{
        border: none;
        padding: 10px;
        background-color: {AppColors.BACKGROUND_DARK};
    }}
    QTabBar::tab {{
        font-size: 10pt;
        font-weight: bold;
        padding: 10px 20px;
        background: {AppColors.BACKGROUND_LIGHT};
        border: 1px solid {AppColors.BORDER};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        color: {AppColors.TEXT_SECONDARY};
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {AppColors.BACKGROUND_DARK};
        color: {AppColors.PRIMARY};
        border-color: {AppColors.BORDER};
    }}
    QHeaderView::section {{
        background-color: {AppColors.PRIMARY};
        color: white;
        padding: 5px;
        border: 1px solid {AppColors.PRIMARY};
        font-weight: bold;
    }}
"""

# =============================================================================
#  --- OPTIMIZED SERIAL THREAD ---
# =============================================================================
class SerialThread(QThread):
    # OPTIMIZATION: Emit a dictionary with batched data, not one signal per line.
    data_received_batch = pyqtSignal(dict) 
    time_sync_data = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.buffer = ""
        self.last_process_time = time.time()
        
        # --- OPTIMIZATION: Logging state is now managed within the thread ---
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
        self.stop_logging() # Ensure logs are closed on disconnect
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.wait() # Wait for the run loop to finish

    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(cmd.encode('utf-8'))
            except Exception as e:
                print(f"Send command error: {e}")

    # --- OPTIMIZATION: Methods to control logging from the main thread ---
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
                    self.running = False # Stop the thread on major serial error
                    break
                except Exception as e:
                    print(f"Serial read error: {e}")

                # Process buffer periodically to avoid overwhelming the system
                current_time = time.time()
                if current_time - self.last_process_time > 0.1:  # Process every 100ms
                    self.process_buffer()
                    self.last_process_time = current_time
            else:
                self.msleep(50) # Sleep longer if not connected

    def process_buffer(self):
        if '\n' not in self.buffer:
            return

        # OPTIMIZATION: Create a batch dictionary to hold all new data
        data_batch = {"UART1": [], "UART2": [], "UART3": [], "UART4": []}
        
        lines, self.buffer = self.buffer.rsplit('\n', 1)
        
        for line in lines.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # --- Handle different data types ---
            if line.startswith('[IC]'):
                self.time_sync_data.emit(line)
            elif line.startswith('['):
                end_bracket = line.find(']')
                if end_bracket != -1:
                    timestamp_mcu = line[1:end_bracket]
                    data_content = line[end_bracket+1:].strip()
                    
                    # Determine UART ID
                    if "$GPGGA" in data_content: uart_id = "UART1"
                    elif "$MYINS" in data_content: uart_id = "UART2"
                    elif "$SDDBT" in data_content: uart_id = "UART3"
                    else: uart_id = "UART4" # Fallback
                    
                    # Add to the batch for UI update
                    data_batch[uart_id].append(data_content)
                    
                    # --- OPTIMIZATION: Perform logging directly in the worker thread ---
                    if self.logging_active:
                        try:
                            # Open file on first write
                            if uart_id not in self.log_files:
                                filename = os.path.join(self.log_folder, f"{uart_id.lower()}.csv")
                                self.log_files[uart_id] = open(filename, 'w', newline='', encoding='utf-8')
                                writer = csv.writer(self.log_files[uart_id])
                                writer.writerow(["PC Timestamp", "Raw Data"])

                            pc_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                            writer = csv.writer(self.log_files[uart_id])
                            writer.writerow([pc_timestamp, data_content])
                        except (IOError, csv.Error) as e:
                            print(f"Error writing to log for {uart_id}: {e}")

        # --- OPTIMIZATION: Emit a single signal with the entire batch ---
        # Filter out empty lists before emitting
        non_empty_batch = {k: v for k, v in data_batch.items() if v}
        if non_empty_batch:
            self.data_received_batch.emit(non_empty_batch)

        # Safety net for buffer size
        if len(self.buffer) > 20000:
            self.buffer = self.buffer[-10000:]

# =============================================================================
#  --- "REALTERM-STYLE" MAIN PAGE ---
# =============================================================================
class MainPage(QWidget):
    # Define a constant for the fixed number of lines to display
    DISPLAY_LINE_COUNT = 10

    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.logging_active = False

        # OPTIMIZATION: Use deque for a high-performance, fixed-size, "rolling" buffer
        self.data_buffers = {
            f"UART{i}": deque(maxlen=self.DISPLAY_LINE_COUNT) for i in range(1, 5)
        }
        
        self.init_ui()
        
        # UI update timer remains a good practice to throttle updates
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_displays)
        self.update_timer.start(100)  # Update UI 10 times per second

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- Top Control Panel (Connection and Logging) ---
        control_grid = QGridLayout()
        control_grid.setSpacing(20)

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
        control_grid.addWidget(com_group, 0, 0)
        
        # Logging Section - FIXED: Moved inside init_ui
        log_group = QGroupBox("Data Logging")
        log_layout = QHBoxLayout()
        self.log_status = QLabel("INACTIVE")
        self.update_log_status_style(active=False)
        log_layout.addWidget(self.log_status)
        log_layout.addStretch()
        self.log_btn = QPushButton("Start Logging")  # CREATE log_btn HERE
        self.log_btn.clicked.connect(self.toggle_logging)
        self.update_log_button_style(active=False)
        self.log_btn.setEnabled(False) # Disabled until connected
        log_layout.addWidget(self.log_btn)
        log_group.setLayout(log_layout)
        control_grid.addWidget(log_group, 0, 1)
        
        main_layout.addLayout(control_grid)

        # --- UART Data Displays ---
        uart_group = QGroupBox("Live UART Data Streams (Last 10 lines)")
        uart_layout = QGridLayout()
        self.uart_displays = {}
        for i in range(1, 5):
            text_edit = QPlainTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Consolas", 10))
            text_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            # OPTIMIZATION: Prevent scrolling for the "Realterm" feel
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
        
        # Connect to the new batched signal
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
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.DANGER}; border-color: {AppColors.DANGER};")
            self.log_btn.setEnabled(True)
        else:
            self.connect_btn.setText("Connect")
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.SUCCESS}; border-color: {AppColors.SUCCESS};")
            self.log_btn.setEnabled(False)
            # Stop logging if it was active
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
            self.log_status.setStyleSheet(f"color: {AppColors.SUCCESS}; font-weight: bold; font-size: 11pt;")
        else:
            self.log_status.setText("INACTIVE")
            self.log_status.setStyleSheet(f"color: {AppColors.DANGER}; font-weight: bold; font-size: 11pt;")

    def update_log_button_style(self, active):
        if active:
            self.log_btn.setText("Stop Logging")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.DANGER}; border-color: {AppColors.DANGER};")
        else:
            self.log_btn.setText("Start Logging")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.PRIMARY}; border-color: {AppColors.PRIMARY};")

    def toggle_logging(self):
        self.logging_active = not self.logging_active
        self.update_log_status_style(self.logging_active)
        self.update_log_button_style(self.logging_active)

        if self.logging_active:
            # Tell the worker thread to start logging
            log_folder = datetime.now().strftime("%Y%m%d_%H%M%S_logs")
            os.makedirs(log_folder, exist_ok=True)
            self.serial_thread.start_logging(log_folder)
        else:
            # Tell the worker thread to stop logging
            self.serial_thread.stop_logging()

    # OPTIMIZATION: This slot handles the batched data from the thread
    def handle_serial_data_batch(self, data_batch):
        """
        Processes a batch of data. This is called infrequently and is very fast.
        It simply extends the deques with new data.
        """
        for uart_id, data_list in data_batch.items():
            if uart_id in self.data_buffers:
                self.data_buffers[uart_id].extend(data_list)

    # OPTIMIZATION: This function is called by a timer to update the UI
    def update_displays(self):
        """
        Periodically updates the GUI text boxes.
        This is decoupled from the data arrival rate.
        """
        for uart_id, display in self.uart_displays.items():
            buffer = self.data_buffers[uart_id]
            if buffer:
                # Join the last N lines from the deque and set the text.
                # setPlainText is much faster than append for replacing content.
                display_text = "\n".join(buffer)
                display.setPlainText(display_text)

# =============================================================================
#  --- MONITORING & TIME SYNC PAGES (UNCHANGED BUT BENEFIT FROM OPTIMIZATIONS) ---
#  (These pages will now be more responsive because the underlying data
#  handling in the SerialThread and MainPage is much more efficient.)
# =============================================================================

class MonitoringPage(QWidget):
    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.init_ui()
        serial_thread.data_received_batch.connect(self.process_data_batch)
        
        # Data buffers for graphing
        self.depth_data = deque(maxlen=100)
        self.roll_data = deque(maxlen=100)
        self.pitch_data = deque(maxlen=100)
        self.heading_data = deque(maxlen=100)
        self.timestamps = deque(maxlen=100)
        self.last_update = 0

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
        self.graph_timer.start(500)  # Update graphs twice per second

    def process_data_batch(self, data_batch):
        current_time = time.time()
        # Process only the last relevant message from each list in the batch
        for uart_id, data_list in data_batch.items():
            if data_list:
                self.process_data(uart_id, data_list[-1])
        
        # Update status
        time_since_last = current_time - self.last_update
        if time_since_last > 5:  # 5 seconds without data
            self.status_label.setText("No data received recently")
            self.status_label.setStyleSheet("font-weight: bold; color: #e74c3c;")
        elif time_since_last > 2:  # 2 seconds without data
            self.status_label.setText("Data connection slow")
            self.status_label.setStyleSheet("font-weight: bold; color: #f39c12;")
        else:
            self.status_label.setText("Receiving data")
            self.status_label.setStyleSheet("font-weight: bold; color: #2ecc71;")
            
        self.last_update = current_time

    def process_data(self, uart_id, data):
        try:
            # Debug output to diagnose issues
            # print(f"Processing {uart_id}: {data}")
            
            if uart_id == "UART1" and data.startswith('$GPGGA'):
                parts = data.split(',')
                if len(parts) > 9 and parts[1] and parts[2] and parts[4]:
                    # Parse time (HHMMSS.SS format)
                    time_str = parts[1]
                    if '.' in time_str:
                        time_str = time_str.split('.')[0]  # Remove fractional seconds
                    
                    # Format time as HH:MM:SS
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
                    
                    # Update position display
                    self.param_labels["Position"].setText(f"{latitude:.6f}, {longitude:.6f}")
            
            elif uart_id == "UART2" and data.startswith('$MYINS'):
                parts = data.split(',')
                if len(parts) >= 4:
                    # Extract values and remove any checksum (*XX)
                    roll = parts[1].split('*')[0].strip()
                    pitch = parts[2].split('*')[0].strip()
                    heading = parts[3].split('*')[0].strip()
                    
                    # Update attitude display
                    self.param_labels["Attitude"].setText(f"R: {roll}°  P: {pitch}°  H: {heading}°")
                    
                    # Store values for graphing
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
                    # Extract depth value and remove any checksum (*XX)
                    depth = parts[3].split('*')[0].strip()
                    self.param_labels["Depth"].setText(f"{depth} m")
                    
                    # Store depth for graphing
                    try:
                        self.depth_data.append(float(depth))
                    except ValueError:
                        pass
        
        except (ValueError, IndexError, TypeError) as e:
            print(f"Error processing dashboard data: {e}\nRaw data: {data}")

    def update_graphs(self):
        """Update the depth and attitude graphs"""
        # Update depth graph
        if self.depth_data:
            self.depth_curve.setData(list(self.depth_data))
        
        # Update attitude graph
        if self.roll_data and self.pitch_data and self.heading_data and self.timestamps:
            # Convert timestamps to relative seconds
            if self.timestamps:
                base_time = self.timestamps[0]
                rel_times = [t - base_time for t in self.timestamps]
                
                self.roll_curve.setData(rel_times, list(self.roll_data))
                self.pitch_curve.setData(rel_times, list(self.pitch_data))
                self.heading_curve.setData(rel_times, list(self.heading_data))

class TimeSyncPage(QWidget):
    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.time_data = []
        self.max_data_points = 100
        self.init_ui()
        serial_thread.time_sync_data.connect(self.process_time_sync)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(500)

    def init_ui(self):
        main_layout = QGridLayout(self)
        main_layout.setSpacing(15)
        control_group = QGroupBox("Time Sync Control")
        control_layout = QHBoxLayout(control_group)
        self.gettime_btn = QPushButton("Start Stream")
        self.gettime_btn.clicked.connect(lambda: self.serial_thread.send_command("GETTIME\r\n"))
        control_layout.addWidget(self.gettime_btn)
        self.stop_btn = QPushButton("Stop Stream")
        self.stop_btn.setStyleSheet(f"background-color: {AppColors.WARNING}; border-color: {AppColors.WARNING};")
        self.stop_btn.clicked.connect(lambda: self.serial_thread.send_command("STOP_GETTIME\r\n"))
        control_layout.addWidget(self.stop_btn)
        control_layout.addStretch()
        self.sync_status_label = QLabel("Status: Awaiting Data")
        self.sync_status_label.setStyleSheet("font-size: 11pt; font-weight: bold;")
        control_layout.addWidget(self.sync_status_label)
        main_layout.addWidget(control_group, 0, 0, 1, 2)
        plot_group = QGroupBox("Time Sync Performance (µs)")
        plot_layout = QVBoxLayout(plot_group)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', "Capture Value (µs)", color=AppColors.TEXT_PRIMARY)
        self.plot_widget.setLabel('bottom', "Sample Number", color=AppColors.TEXT_PRIMARY)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.getAxis('left').setTextPen(AppColors.TEXT_PRIMARY)
        self.plot_widget.getAxis('bottom').setTextPen(AppColors.TEXT_PRIMARY)
        plot_layout.addWidget(self.plot_widget)
        self.plot_curve = self.plot_widget.plot(pen=pg.mkPen(color=AppColors.PRIMARY, width=2))
        self.locked_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(QColor(AppColors.SUCCESS)))
        self.unlocked_points = pg.ScatterPlotItem(size=10, pen=pg.mkPen(None), brush=pg.mkBrush(QColor(AppColors.DANGER)))
        self.plot_widget.addItem(self.locked_points)
        self.plot_widget.addItem(self.unlocked_points)
        main_layout.addWidget(plot_group, 1, 0, 1, 2)
        stats_group = QGroupBox("Statistics")
        stats_layout = QHBoxLayout(stats_group)
        self.avg_label = QLabel("Avg: -")
        self.max_label = QLabel("Max: -")
        self.min_label = QLabel("Min: -")
        self.lock_label = QLabel("Lock: -")
        for label in [self.avg_label, self.max_label, self.min_label, self.lock_label]:
            label.setStyleSheet("font-size: 10pt; font-weight: bold;")
            stats_layout.addWidget(label, 1, Qt.AlignCenter)
        main_layout.addWidget(stats_group, 2, 0)
        clear_btn = QPushButton("Clear Plot")
        clear_btn.clicked.connect(self.clear_data)
        main_layout.addWidget(clear_btn, 2, 1, Qt.AlignRight)

    def clear_data(self):
        self.time_data.clear()
        self.plot_curve.clear()
        self.locked_points.clear()
        self.unlocked_points.clear()
        self.avg_label.setText("Avg: -")
        self.max_label.setText("Max: -")
        self.min_label.setText("Min: -")
        self.lock_label.setText("Lock: -")
        self.sync_status_label.setText("Status: Cleared")

    def process_time_sync(self, data):
        try:
            # Debug output to diagnose issues
            print(f"Raw time sync data: {data}")
            
            parts = data.split()
            if len(parts) >= 6:
                value = int(parts[1])
                is_locked = (parts[5] == "YES")
                self.time_data.append({'value': value, 'locked': is_locked})
                if len(self.time_data) > self.max_data_points:
                    self.time_data.pop(0)
                status_text = "LOCKED" if is_locked else "UNLOCKED"
                status_color = AppColors.SUCCESS if is_locked else AppColors.DANGER
                self.sync_status_label.setText(f"Status: Streaming ({status_text})")
                self.sync_status_label.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {status_color};")
                self.lock_label.setText(f"Lock: {status_text}")
                self.lock_label.setStyleSheet(f"font-size: 10pt; font-weight: bold; color: {status_color};")
        except (ValueError, IndexError) as e:
            print(f"Error parsing time sync data '{data}': {e}")

    def update_plot(self):
        if not self.time_data:
            return
        values = [d['value'] for d in self.time_data]
        self.plot_curve.setData(values)
        locked_x, locked_y = [], []
        unlocked_x, unlocked_y = [], []
        for i, d in enumerate(self.time_data):
            if d['locked']:
                locked_x.append(i)
                locked_y.append(d['value'])
            else:
                unlocked_x.append(i)
                unlocked_y.append(d['value'])
        self.locked_points.setData(locked_x, locked_y)
        self.unlocked_points.setData(unlocked_x, unlocked_y)
        self.avg_label.setText(f"Avg: {sum(values) / len(values):.1f}")
        self.max_label.setText(f"Max: {max(values)}")
        self.min_label.setText(f"Min: {min(values)}")
        
# =============================================================================
#  --- MAIN WINDOW & ENTRY POINT ---
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
        self.time_sync_page = TimeSyncPage(self.serial_thread)
        
        self.tabs.addTab(self.main_page, "Logging")
        self.tabs.addTab(self.monitoring_page, "Monitoring")
        self.tabs.addTab(self.time_sync_page, "Sync Info")
        
        self.setCentralWidget(self.tabs)
        
        # Connect tab change signal
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index):
        """Optimize resource usage based on active tab"""
        if index == 0:  # Logging tab
            # Enable logging, disable monitoring parsing
            pass
        elif index == 1:  # Monitoring tab
            # Disable logging to free resources for parsing
            if self.main_page.logging_active:
                self.main_page.toggle_logging()
        elif index == 2:  # Time Sync tab
            # No special handling needed
            pass

    def closeEvent(self, event):
        print("Closing application. Cleaning up resources...")
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())