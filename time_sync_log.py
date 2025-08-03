import sys
import os
import csv
import serial
import time
import serial.tools.list_ports
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QComboBox, QPlainTextEdit, QGroupBox, 
    QStyle, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

# =============================================================================
# --- APPLICATION STYLING AND CONSTANTS ---
# =============================================================================
class AppColors:
    PRIMARY = "#3498db"
    SECONDARY = "#2980b9"
    BACKGROUND_LIGHT = "#f4f6f8"
    TEXT_PRIMARY = "#2c3e51"
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
        min-width: 120px;
    }}
    QPushButton:hover {{
        background-color: {AppColors.SECONDARY};
        border-color: {AppColors.SECONDARY};
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
    QPlainTextEdit {{
        border: 1px solid {AppColors.BORDER};
        border-radius: 5px;
        background-color: #ffffff;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 11pt;
    }}
"""

# =============================================================================
# --- SIMPLIFIED SERIAL THREAD ---
# =============================================================================
class SerialThread(QThread):
    """
    This thread handles serial communication and parses incoming data.
    It specifically looks for lines with "$GPGGA" to extract DAQ and UTC times.
    """
    # Signal emits UTC time (string) and DAQ time (string)
    data_received = pyqtSignal(str, str)
    connection_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.buffer = ""

    def connect(self, port, baudrate=115200):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        try:
            self.serial_port = serial.Serial(port, baudrate=baudrate, timeout=0.1)
            self.running = True
            self.buffer = ""
            return True
        except serial.SerialException as e:
            self.connection_error.emit(f"Failed to open {port}: {e}")
            return False

    def disconnect(self):
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.serial_port = None
        self.wait() # Wait for the thread to finish cleanly

    def send_command(self, cmd):
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(cmd.encode('utf-8'))
            except Exception as e:
                print(f"Send command error: {e}")

    def run(self):
        while self.running:
            if not self.serial_port or not self.serial_port.is_open:
                self.msleep(100)
                continue
            
            try:
                # Read available data, non-blocking
                data = self.serial_port.read(self.serial_port.in_waiting or 1)
                if data:
                    self.buffer += data.decode('ascii', errors='ignore')
                    self.process_buffer()
            except serial.SerialException:
                # Port was disconnected
                self.connection_error.emit("Device disconnected.")
                self.running = False
                break
            # Small sleep to yield CPU time if no data is coming in
            self.msleep(10)

    def process_buffer(self):
        # Process lines separated by newline characters
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            line = line.strip()

            # The target data format is: [<DAQ_Time>] $GPGGA,<UTC_Time>,...
            if "$GPGGA" in line and line.startswith('[') and ']' in line:
                try:
                    # 1. Parse the DAQ Time
                    end_bracket_pos = line.find(']')
                    daq_time = line[1:end_bracket_pos]

                    # 2. Parse the UTC Time from the GPGGA sentence
                    parts = line.split(',')
                    if len(parts) > 1 and parts[1]:
                        utc_raw = parts[1]
                        # Format to HH:MM:SS.ffffff
                        if '.' in utc_raw:
                            time_part, ms_part = utc_raw.split('.')
                        else:
                            time_part, ms_part = utc_raw, "0"
                        
                        h = time_part[0:2]
                        m = time_part[2:4]
                        s = time_part[4:6]
                        # Pad microseconds to 6 digits
                        ms_part_padded = ms_part.ljust(6, '0')

                        utc_formatted = f"{h}:{m}:{s}.{ms_part_padded}"
                        
                        # Emit the parsed data
                        self.data_received.emit(utc_formatted, daq_time)

                except (ValueError, IndexError) as e:
                    # Silently ignore malformed lines to keep the log clean
                    # print(f"Could not parse line: {line} | Error: {e}")
                    pass

# =============================================================================
# --- MAIN APPLICATION WINDOW ---
# =============================================================================
class TimeSyncLoggerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Time Sync Logger")
        self.setWindowIcon(QIcon(self.style().standardIcon(QStyle.SP_ComputerIcon)))
        self.setGeometry(100, 100, 800, 600)

        # --- State Variables ---
        self.is_logging = False
        self.is_sync_running = False
        self.log_file = None
        self.csv_writer = None

        # --- Business Logic ---
        self.serial_thread = SerialThread()
        self.serial_thread.data_received.connect(self.update_log)
        self.serial_thread.connection_error.connect(self.handle_connection_error)

        # --- UI Setup ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        
        self.setup_ui()

    def setup_ui(self):
        # Create UI sections
        connection_group = self.create_connection_group()
        control_group = self.create_control_group()
        
        # Log Display
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        
        # Add widgets to main layout
        self.main_layout.addWidget(connection_group)
        self.main_layout.addWidget(control_group)
        self.main_layout.addWidget(self.log_display, 1) # Give it stretch factor

        self.update_ui_state()

    def create_connection_group(self):
        group = QGroupBox("Serial Connection")
        layout = QHBoxLayout(group)
        
        layout.addWidget(QLabel("COM Port:"))
        self.com_combo = QComboBox()
        layout.addWidget(self.com_combo, 1)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        layout.addWidget(self.refresh_btn)
        
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn)

        self.refresh_ports()
        return group

    def create_control_group(self):
        group = QGroupBox("Controls")
        layout = QHBoxLayout(group)
        
        self.sync_btn = QPushButton("Start Time Sync")
        self.sync_btn.clicked.connect(self.toggle_time_sync)
        layout.addWidget(self.sync_btn)
        
        self.log_btn = QPushButton("Start Logging")
        self.log_btn.clicked.connect(self.toggle_logging)
        layout.addWidget(self.log_btn)
        
        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addStretch()
        layout.addWidget(self.status_label)

        return group

    # --- UI State Management ---
    def update_ui_state(self):
        is_connected = self.serial_thread.isRunning()
        
        # Connection controls
        self.com_combo.setEnabled(not is_connected)
        self.refresh_btn.setEnabled(not is_connected)
        self.connect_btn.setText("Disconnect" if is_connected else "Connect")
        
        if is_connected:
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.DANGER};")
        else:
            self.connect_btn.setStyleSheet(f"background-color: {AppColors.SUCCESS};")

        # Sync and Log controls
        self.sync_btn.setEnabled(is_connected)
        self.log_btn.setEnabled(is_connected)
        
        # Update status label
        status_text = "Status: "
        if is_connected:
            status_text += "Connected"
            if self.is_sync_running:
                status_text += " | Streaming"
            if self.is_logging:
                status_text += " | Logging to CSV"
        else:
            status_text = "Status: Disconnected"
        self.status_label.setText(status_text)
    
    # --- Button Click Handlers & Logic ---
    def refresh_ports(self):
        self.com_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.com_combo.addItems(ports)
        else:
            self.com_combo.addItem("No ports found")

    def toggle_connection(self):
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect()
            if self.is_sync_running:
                self.toggle_time_sync() # Ensure it stops
            if self.is_logging:
                self.toggle_logging() # Ensure file is closed
        else:
            port = self.com_combo.currentText()
            if "No ports" not in port:
                if self.serial_thread.connect(port):
                    self.serial_thread.start()
                    self.log_display.clear()
        self.update_ui_state()

    def handle_connection_error(self, message):
        """Called when serial port disconnects unexpectedly."""
        print(f"Connection Error: {message}")
        if self.is_logging:
            self.stop_logging_procedure()
        
        self.is_sync_running = False
        self.sync_btn.setText("Start Time Sync")
        self.sync_btn.setStyleSheet(f"background-color: {AppColors.PRIMARY};")
        
        self.serial_thread.disconnect() # Ensure thread is fully stopped
        self.update_ui_state()


    def toggle_time_sync(self):
        self.is_sync_running = not self.is_sync_running
        if self.is_sync_running:
            self.serial_thread.send_command("GETTIME\n")
            self.sync_btn.setText("Stop Time Sync")
            self.sync_btn.setStyleSheet(f"background-color: {AppColors.WARNING};")
        else:
            self.serial_thread.send_command("STOP_GETTIME\n")
            self.sync_btn.setText("Start Time Sync")
            self.sync_btn.setStyleSheet(f"background-color: {AppColors.PRIMARY};")
        self.update_ui_state()

    def toggle_logging(self):
        if not self.is_logging:
            # Start logging
            default_filename = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filename, _ = QFileDialog.getSaveFileName(self, "Save Log File", default_filename, "CSV Files (*.csv)")
            
            if filename:
                try:
                    self.log_file = open(filename, 'w', newline='', encoding='utf-8')
                    self.csv_writer = csv.writer(self.log_file)
                    # Write header
                    self.csv_writer.writerow(["UTC_Time", "DAQ_Time"])
                    self.is_logging = True
                    self.log_btn.setText("Stop Logging")
                    self.log_btn.setStyleSheet(f"background-color: {AppColors.DANGER};")
                except IOError as e:
                    print(f"Error opening file: {e}")
                    self.log_file = None
                    self.csv_writer = None
        else:
            # Stop logging
            self.stop_logging_procedure()
        
        self.update_ui_state()

    def stop_logging_procedure(self):
        """Safely closes the log file and resets state."""
        if self.log_file:
            self.log_file.close()
            print("Log file closed.")
        self.log_file = None
        self.csv_writer = None
        self.is_logging = False
        self.log_btn.setText("Start Logging")
        self.log_btn.setStyleSheet(f"background-color: {AppColors.SUCCESS};")

    def update_log(self, utc_time, daq_time):
        """Receives data from the serial thread and updates UI/logs."""
        log_line = f"{utc_time},{daq_time}"
        
        # Append to the on-screen display
        self.log_display.appendPlainText(log_line)
        
        # Write to CSV if logging is active
        if self.is_logging and self.csv_writer:
            try:
                self.csv_writer.writerow([utc_time, daq_time])
            except (IOError, csv.Error) as e:
                print(f"Error writing to log file: {e}")
                # Stop logging to prevent further errors
                self.toggle_logging()

    def closeEvent(self, event):
        """Ensure clean shutdown."""
        print("Closing application...")
        if self.is_logging:
            self.stop_logging_procedure()
        if self.serial_thread.isRunning():
            self.serial_thread.disconnect()
        event.accept()

# =============================================================================
# --- ENTRY POINT ---
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    
    window = TimeSyncLoggerApp()
    window.show()
    
    sys.exit(app.exec_())