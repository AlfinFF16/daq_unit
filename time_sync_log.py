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
        self.timesync_file = None
        print(f"Logging started in thread. Folder: {self.log_folder}")

    def stop_logging(self):
        self.logging_active = False
        if self.timesync_file:
            self.timesync_file.close()
            self.timesync_file = None
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
                # Log time sync data if logging is active
                if self.logging_active:
                    try:
                        if not self.timesync_file:
                            filename = os.path.join(self.log_folder, "timesync.csv")
                            self.timesync_file = open(filename, 'w', newline='', encoding='utf-8')
                            writer = csv.writer(self.timesync_file)
                            writer.writerow(["PC Timestamp", "Raw Data"])
                        
                        pc_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        writer = csv.writer(self.timesync_file)
                        writer.writerow([pc_timestamp, line])
                        self.timesync_file.flush()  # Ensure data is written immediately
                    except (IOError, csv.Error) as e:
                        print(f"Error writing to timesync log: {e}")
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


class TimeSyncPage(QWidget):
    # This class also remains the same, but will be more responsive.
    def __init__(self, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread
        self.time_data = []
        self.logging_active = False
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
        self.gettime_btn.clicked.connect(lambda: self.serial_thread.send_command("GETTIME\n"))
        control_layout.addWidget(self.gettime_btn)
        self.stop_btn = QPushButton("Stop Stream")
        self.stop_btn.setStyleSheet(f"background-color: {AppColors.WARNING}; border-color: {AppColors.WARNING};")
        self.stop_btn.clicked.connect(lambda: self.serial_thread.send_command("STOP_GETTIME\n"))
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
        # Add log button to control group
        self.log_btn = QPushButton("Log to CSV")
        self.log_btn.setCheckable(True)
        self.log_btn.clicked.connect(self.toggle_logging)
        control_layout.addWidget(self.log_btn)
        
        # Add log status indicator
        self.log_status = QLabel("Logging: OFF")
        self.log_status.setStyleSheet("color: red; font-weight: bold;")
        control_layout.addWidget(self.log_status)
    
    def toggle_logging(self):
        self.logging_active = not self.logging_active
        if self.logging_active:
            self.log_btn.setText("Stop Logging")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.DANGER};")
            self.log_status.setText("Logging: ACTIVE")
            self.log_status.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.log_btn.setText("Log to CSV")
            self.log_btn.setStyleSheet(f"background-color: {AppColors.PRIMARY};")
            self.log_status.setText("Logging: OFF")
            self.log_status.setStyleSheet("color: red; font-weight: bold;")

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
            # Write to CSV if logging is active
            if self.logging_active:
                log_folder = self.serial_thread.log_folder
                if log_folder and self.serial_thread.logging_active:
                    try:
                        filename = os.path.join(log_folder, "timesync_processed.csv")
                        file_exists = os.path.isfile(filename)
                        
                        with open(filename, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.writer(f)
                            if not file_exists:
                                writer.writerow(["PC Timestamp", "Capture Value", "Lock Status"])
                            
                            pc_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                            lock_status = "LOCKED" if is_locked else "UNLOCKED"
                            writer.writerow([pc_timestamp, value, lock_status])
                    except (IOError, csv.Error) as e:
                        print(f"Error writing to processed timesync log: {e}")
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
        self.time_sync_page = TimeSyncPage(self.serial_thread)
        
        self.tabs.addTab(self.main_page, "Logging")
        self.tabs.addTab(self.time_sync_page, "Sync Info")
        
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event):
        print("Closing application. Cleaning up resources...")
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect() # This now handles stopping logging and waiting for the thread
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())